from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Cliente,
    DeudaSimple,
    DeudaSimpleEstado,
    Moneda,
)
from app.core.fechas import hoy_local
from app.schemas.cheques import ChequeRead
from app.schemas.deudas_simples import (
    DeudaSimpleCobrarConChequeRequest,
    DeudaSimpleCobrarConChequeResponse,
    DeudaSimpleCobroClienteChequeCreate,
    DeudaSimpleCobroClienteChequeResponse,
    DeudaSimpleCobroClienteCreate,
    DeudaSimpleCobroClienteResponse,
    DeudaSimpleCreate,
    DeudaSimplePagoRequest,
    DeudaSimpleRead,
    DeudaSimpleUpdate,
)
from app.services import caja as svc_caja
from app.services import pasivos as svc_pasivos
from app.services.conversion import calcular_reduccion_saldo, convertir_a_moneda_deuda
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

# referencia_tipo del EGRESO de origen (el alta) y del INGRESO de cada cobro. Se
# distinguen para que la edición pueda resincronizar SOLO el egreso de origen sin
# tocar las líneas de los cobros ya hechos (ambos apuntan al mismo id de deuda).
_CIEN = Decimal("100")

_REF_ORIGEN = "deuda_simple"
_REF_COBRO = "deuda_simple_cobro"


def aplicar_cobro(
    saldo_pendiente: Decimal, reduccion: Decimal
) -> tuple[Decimal, bool]:
    """Nuevo saldo y si la deuda quedó cancelada, tras imputar una `reduccion`.

    `reduccion` es cuánto baja el saldo (en la moneda de la deuda); ya viene
    validada y topeada al saldo por `calcular_reduccion_saldo`. Pura (sin BD):
    testeable en el estilo de `tests/`."""
    nuevo = (saldo_pendiente - reduccion).quantize(Decimal("0.01"))
    return nuevo, nuevo == Decimal("0.00")


def repartir_cobro_fifo(
    saldos: list[Decimal], reduccion: Decimal, efectivo: Decimal
) -> list[tuple[Decimal, Decimal]]:
    """Reparte un cobro entre las deudas de un cliente, en el orden recibido.

    `saldos` son los saldos pendientes de las deudas abiertas, ordenados como se
    quiera imputar (la más vieja primero). `reduccion` es cuánto baja el saldo en
    total (en la moneda de las deudas) y `efectivo` es la plata que realmente
    entró (en la moneda cobrada, que puede ser otra). Devuelve por deuda
    `(imputado, efectivo)`: lo primero baja su saldo, lo segundo es el monto de
    **su** línea de caja.

    Se reparten las **dos** magnitudes porque cada deuda asienta su propia línea
    `COBRO_DEUDA` (anular una deuda borra sus líneas por referencia; una línea
    compartida entre dos deudas se llevaría puesta plata de la otra). En un cobro
    cross-moneda el efectivo se prorratea por lo imputado, y **el residuo del
    redondeo cae en la última deuda alcanzada**: así la suma de las líneas es
    exactamente lo que entró y la caja del día no cierra por unos centavos menos.

    Pura (sin BD): testeable en el estilo de `tests/`."""
    cero = Decimal("0.00")
    centavo = Decimal("0.01")

    imputado: list[Decimal] = []
    restante = reduccion
    for saldo in saldos:
        disponible = saldo if saldo > cero else cero
        aplica = min(restante, disponible) if restante > cero else cero
        aplica = aplica.quantize(centavo)
        imputado.append(aplica)
        restante = (restante - aplica).quantize(centavo)

    alcanzadas = [i for i, aplica in enumerate(imputado) if aplica > cero]
    if not alcanzadas:
        return [(cero, cero) for _ in saldos]

    total_imputado = sum(imputado, cero)
    ultima = alcanzadas[-1]
    repartido: list[tuple[Decimal, Decimal]] = []
    acumulado = cero
    for i, aplica in enumerate(imputado):
        if aplica <= cero:
            repartido.append((cero, cero))
            continue
        if i == ultima:
            plata = (efectivo - acumulado).quantize(centavo)
        else:
            plata = (efectivo * aplica / total_imputado).quantize(centavo)
            acumulado = (acumulado + plata).quantize(centavo)
        repartido.append((aplica, plata))
    return repartido


def calcular_imputacion_y_vuelto(
    moneda_deuda: Moneda,
    saldo_total: Decimal,
    valor_neto_cheque: Decimal,
    cotizacion: Decimal | None,
) -> tuple[Decimal, Decimal]:
    """Cuánto salda un cheque de la deuda total de un cliente y cuánto sobra.

    Devuelve `(imputado, diferencia)`. `imputado` va en la moneda de las deudas y
    está topeado al saldo total: nunca deja saldos negativos. `diferencia` va en
    **ARS** aunque las deudas sean en dólares, porque el excedente de un cheque
    es plata en pesos y en pesos se resuelve el vuelto.

    Un cheque que cubre de más **no es un error**: el cliente entrega el que
    tiene. Por eso convierte con `convertir_a_moneda_deuda` (que no topea ni
    valida el exceso) y no con `calcular_reduccion_saldo`, que rechazaría el
    pago. Pura (sin BD): testeable en el estilo de `tests/`."""
    equivalente = convertir_a_moneda_deuda(
        moneda_deuda, Moneda.ARS, valor_neto_cheque, cotizacion
    )
    imputado = min(equivalente, saldo_total)
    sobrante = equivalente - saldo_total
    if sobrante <= Decimal("0.00"):
        return imputado, Decimal("0.00")

    es_cross = moneda_deuda != Moneda.ARS
    diferencia = (sobrante * cotizacion if es_cross else sobrante).quantize(
        Decimal("0.01")
    )
    return imputado, diferencia


def get_deuda_simple(db: Session, deuda_id: uuid.UUID) -> DeudaSimple:
    deuda = db.get(DeudaSimple, deuda_id)
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    return deuda


def list_deudas_simples(
    db: Session, estado: DeudaSimpleEstado | None = None
) -> list[DeudaSimple]:
    query = select(DeudaSimple).where(DeudaSimple.anulado_at.is_(None))
    if estado is not None:
        query = query.where(DeudaSimple.estado == estado)
    return list(db.scalars(query.order_by(DeudaSimple.created_at.desc())))


def _registrar_egreso_origen(db: Session, deuda: DeudaSimple, cliente_nombre: str) -> None:
    """Asienta el EGRESO de caja del alta de la deuda (salió la plata)."""
    svc_caja.registrar(
        db,
        fecha=deuda.fecha,
        moneda=deuda.moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.OTORGAMIENTO_DEUDA,
        monto=deuda.monto,
        referencia_tipo=_REF_ORIGEN,
        referencia_id=deuda.id,
        detalle=f"Deuda de {cliente_nombre} - {deuda.concepto}",
    )


def create_deuda_simple(db: Session, payload: DeudaSimpleCreate) -> DeudaSimple:
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    fecha = payload.fecha or hoy_local()
    deuda = DeudaSimple(
        cliente_id=payload.cliente_id,
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        saldo_pendiente=payload.monto,
        moneda=payload.moneda,
        estado=DeudaSimpleEstado.ABIERTA,
        fecha=fecha,
        observaciones=payload.observaciones,
    )

    try:
        db.add(deuda)
        db.flush()
        _registrar_egreso_origen(db, deuda, cliente.nombre)
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear la deuda.") from exc


def editar_deuda_simple(
    db: Session, deuda_id: uuid.UUID, payload: DeudaSimpleUpdate
) -> DeudaSimple:
    """Corrige la carga de una deuda libre (panel).

    `concepto`, `fecha` y `observaciones` se editan siempre. `monto`/`moneda` solo
    si la deuda está ABIERTA y sin cobros parciales (saldo == monto); cambiarlos
    con cobros hechos desincronizaría la caja. Siempre se resincroniza el EGRESO de
    origen (su monto/moneda/fecha pueden cambiar); las líneas de cobro no se tocan."""
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "moneda" in data
    tiene_cobros = deuda.saldo_pendiente != deuda.monto
    if cambia_dinero and (deuda.estado == DeudaSimpleEstado.CANCELADA or tiene_cobros):
        raise ConflictError(
            "La deuda está cancelada o ya tiene cobros parciales; solo se pueden "
            "editar concepto, fecha y observaciones."
        )

    if "concepto" in data:
        deuda.concepto = data["concepto"].strip()
    if "fecha" in data and data["fecha"] is not None:
        deuda.fecha = data["fecha"]
    if "observaciones" in data:
        deuda.observaciones = data["observaciones"]
    if "moneda" in data:
        deuda.moneda = data["moneda"]
    if "monto" in data:
        # Sin cobros parciales (garantizado arriba): el saldo sigue al monto.
        deuda.monto = data["monto"]
        deuda.saldo_pendiente = data["monto"]

    try:
        # Rehacer solo el egreso de origen (monto/moneda/fecha pueden haber cambiado).
        svc_caja.borrar_por_referencia(db, _REF_ORIGEN, deuda.id)
        cliente_nombre = deuda.cliente.nombre if deuda.cliente else "—"
        _registrar_egreso_origen(db, deuda, cliente_nombre)
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar la deuda.") from exc


def cobrar_deuda_simple(
    db: Session, deuda_id: uuid.UUID, payload: DeudaSimplePagoRequest
) -> DeudaSimple:
    """Cobra una deuda libre (total o parcial), en efectivo.

    La caja recibe la plata en la moneda efectivamente cobrada (`moneda_pago`); el
    saldo baja por el equivalente en la moneda de la deuda (vía cotización si el
    cobro cruza monedas). Cuando el saldo llega a 0, la deuda pasa a CANCELADA."""
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    if deuda.estado == DeudaSimpleEstado.CANCELADA:
        raise ConflictError("La deuda ya está cancelada.")

    es_cross = payload.moneda_pago != deuda.moneda
    reduccion = calcular_reduccion_saldo(
        deuda.moneda,
        deuda.saldo_pendiente,
        payload.moneda_pago,
        payload.monto_cobrado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, reduccion)
    if cancelada:
        deuda.estado = DeudaSimpleEstado.CANCELADA
        deuda.fecha_cancelacion = fecha

    # La primera cotización cross-moneda queda como default editable para próximos cobros.
    if es_cross and deuda.cotizacion_pago is None:
        deuda.cotizacion_pago = payload.cotizacion

    cliente_nombre = deuda.cliente.nombre if deuda.cliente else "—"
    detalle = f"Cobro deuda - {cliente_nombre} - {deuda.concepto}"
    if es_cross:
        detalle += f" ({reduccion} {deuda.moneda.value} @ {payload.cotizacion})"

    # Cobrar la deuda hace entrar plata a la caja en la moneda cobrada (incluye parciales).
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=payload.moneda_pago,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_DEUDA,
        monto=payload.monto_cobrado,
        referencia_tipo=_REF_COBRO,
        referencia_id=deuda.id,
        detalle=detalle,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    try:
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de la deuda.") from exc


def cobrar_deudas_cliente(
    db: Session, payload: DeudaSimpleCobroClienteCreate
) -> DeudaSimpleCobroClienteResponse:
    """Cobra un importe libre contra **todas** las deudas abiertas de un cliente.

    Es el cobro de la fila del cliente en "Otras deudas": el operador recibe la
    plata y no tiene por qué decidir a qué deuda va. Se imputa **de la más vieja
    a la más nueva** (por la fecha de la deuda), mismo criterio que el pago libre
    de un préstamo (`repartir_pago_en_cuotas`, §3).

    Se cobra contra las deudas de **una** moneda (`moneda_deuda`): ARS y USD son
    dos cajas distintas y no se suman. El pago sí puede venir en la otra moneda,
    como en el cobro de una deuda suelta.

    Cada deuda alcanzada asienta **su propia** línea `COBRO_DEUDA` (ver
    `repartir_cobro_fifo`), y la que se salda pasa a CANCELADA."""
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    deudas = list(
        db.scalars(
            select(DeudaSimple)
            .where(
                DeudaSimple.cliente_id == payload.cliente_id,
                DeudaSimple.moneda == payload.moneda_deuda,
                DeudaSimple.estado == DeudaSimpleEstado.ABIERTA,
                DeudaSimple.anulado_at.is_(None),
            )
            .order_by(DeudaSimple.fecha.asc(), DeudaSimple.created_at.asc())
            .with_for_update()
        )
    )
    if not deudas:
        raise ConflictError(
            f"{cliente.nombre} no tiene deudas abiertas en {payload.moneda_deuda.value}."
        )

    saldo_total = sum(
        (d.saldo_pendiente for d in deudas), Decimal("0.00")
    ).quantize(Decimal("0.01"))

    es_cross = payload.moneda_pago != payload.moneda_deuda
    # Cuánto del total (en la moneda de las deudas) salda este cobro; valida la
    # cotización y que no se cobre más de lo que el cliente debe.
    reduccion = calcular_reduccion_saldo(
        payload.moneda_deuda,
        saldo_total,
        payload.moneda_pago,
        payload.monto_cobrado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    repartido = repartir_cobro_fifo(
        [d.saldo_pendiente for d in deudas], reduccion, payload.monto_cobrado
    )

    afectadas: list[DeudaSimple] = []
    canceladas = 0
    for deuda, (imputa, plata) in zip(deudas, repartido):
        if imputa <= Decimal("0.00"):
            continue

        deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, imputa)
        if cancelada:
            deuda.estado = DeudaSimpleEstado.CANCELADA
            deuda.fecha_cancelacion = fecha
            canceladas += 1

        if es_cross and deuda.cotizacion_pago is None:
            deuda.cotizacion_pago = payload.cotizacion

        detalle = f"Cobro deuda - {cliente.nombre} - {deuda.concepto}"
        if es_cross:
            detalle += f" ({imputa} {deuda.moneda.value} @ {payload.cotizacion})"

        # Una deuda ínfima puede quedar en $0,00 al prorratear un cobro
        # cross-moneda: se le imputa el saldo igual, pero no se asienta una línea
        # de caja en cero. El total sigue cerrando (el residuo va a la última).
        if plata > Decimal("0.00"):
            svc_caja.registrar(
                db,
                fecha=fecha,
                moneda=payload.moneda_pago,
                tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.COBRO_DEUDA,
                monto=plata,
                referencia_tipo=_REF_COBRO,
                referencia_id=deuda.id,
                detalle=detalle,
                cotizacion=payload.cotizacion if es_cross else None,
            )

        afectadas.append(deuda)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro del cliente.") from exc

    for deuda in afectadas:
        db.refresh(deuda)

    saldo_restante = (saldo_total - reduccion).quantize(Decimal("0.01"))
    return DeudaSimpleCobroClienteResponse(
        deudas_afectadas=[DeudaSimpleRead.model_validate(d) for d in afectadas],
        imputado=reduccion,
        canceladas=canceladas,
        saldo_restante=saldo_restante,
    )


def cobrar_deudas_cliente_con_cheque(
    db: Session,
    payload: DeudaSimpleCobroClienteChequeCreate,
    created_at: datetime | None = None,
) -> DeudaSimpleCobroClienteChequeResponse:
    """Cobra TODAS las deudas abiertas de un cliente con un solo cheque.

    Es el cobro de la fila del cliente, pero recibiendo un cheque en vez de
    efectivo. El cheque salda por su **valor neto** y se imputa de la deuda más
    vieja a la más nueva, igual que el efectivo.

    **No asienta caja por el cobro**: el cheque entra a cartera y la plata se
    reconoce recién al venderlo o cobrarlo (mismo criterio que §2, §3 y el cobro
    con cheque de una deuda suelta).

    **Un cheque que cubre de más es el caso normal**, no un error: el cliente
    entrega el cheque que tiene. Por eso se convierte con
    `convertir_a_moneda_deuda` (sin topear) y el excedente se resuelve con
    `svc_pasivos.aplicar_vuelto_cheque`, el mismo mecanismo que el vuelto de un
    pasivo (§5): o se le paga en efectivo —lo único que mueve la caja acá— o el
    negocio le queda debiendo y se crea un pasivo a su favor."""
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    deudas = list(
        db.scalars(
            select(DeudaSimple)
            .where(
                DeudaSimple.cliente_id == payload.cliente_id,
                DeudaSimple.moneda == payload.moneda_deuda,
                DeudaSimple.estado == DeudaSimpleEstado.ABIERTA,
                DeudaSimple.anulado_at.is_(None),
            )
            .order_by(DeudaSimple.fecha.asc(), DeudaSimple.created_at.asc())
            .with_for_update()
        )
    )
    if not deudas:
        raise ConflictError(
            f"{cliente.nombre} no tiene deudas abiertas en {payload.moneda_deuda.value}."
        )

    # Solo choca contra cheques vivos: uno anulado libera su número (migración 0017).
    ya_existe = db.scalar(
        select(Cheque).where(
            Cheque.nro_cheque == payload.nro_cheque_pago,
            Cheque.banco == payload.banco_pago,
            Cheque.anulado_at.is_(None),
        )
    )
    if ya_existe is not None:
        banco_txt = f" del banco {payload.banco_pago}" if payload.banco_pago else ""
        raise ConflictError(
            f"Ya existe un cheque Nº '{payload.nro_cheque_pago}'{banco_txt}."
        )

    saldo_total = sum(
        (d.saldo_pendiente for d in deudas), Decimal("0.00")
    ).quantize(Decimal("0.01"))

    valor_neto = (
        payload.monto_cheque
        * (_CIEN - payload.porcentaje_compra_cheque)
        / _CIEN
    ).quantize(Decimal("0.01"))

    es_cross = payload.moneda_deuda != Moneda.ARS
    reduccion, diferencia = calcular_imputacion_y_vuelto(
        payload.moneda_deuda, saldo_total, valor_neto, payload.cotizacion
    )
    if diferencia > Decimal("0.00") and payload.vuelto_modo is None:
        raise ValidationError(
            f"El cheque cubre toda la deuda y sobran ${diferencia}. Indicá qué "
            "hacer con el vuelto: pagarlo en efectivo o quedar debiéndolo."
        )

    fecha = payload.fecha_cobro or hoy_local()

    cheque_nuevo = Cheque(
        nro_cheque=payload.nro_cheque_pago,
        banco=payload.banco_pago,
        monto=payload.monto_cheque,
        porcentaje_compra=payload.porcentaje_compra_cheque,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        estado=ChequeEstado.EN_CARTERA,
        ganancia=Decimal("0.00"),
        cliente_origen_id=cliente.id,
    )
    if created_at is not None:
        cheque_nuevo.created_at = created_at
    # db.add() y no create_cheque(): recibir un cheque como pago NO es comprarlo,
    # así que no corresponde el egreso COMPRA_CHEQUE.
    db.add(cheque_nuevo)
    db.flush()  # necesita id para la referencia de caja del vuelto

    # El cheque no mueve caja, así que acá solo se imputan saldos: el segundo
    # elemento del reparto (el efectivo por deuda) no se usa.
    repartido = repartir_cobro_fifo(
        [d.saldo_pendiente for d in deudas], reduccion, Decimal("0.00")
    )

    afectadas: list[DeudaSimple] = []
    canceladas = 0
    for deuda, (imputa, _sin_caja) in zip(deudas, repartido):
        if imputa <= Decimal("0.00"):
            continue
        deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, imputa)
        if cancelada:
            deuda.estado = DeudaSimpleEstado.CANCELADA
            deuda.fecha_cancelacion = fecha
            canceladas += 1
        if es_cross and deuda.cotizacion_pago is None:
            deuda.cotizacion_pago = payload.cotizacion
        afectadas.append(deuda)

    if diferencia > Decimal("0.00"):
        svc_pasivos.aplicar_vuelto_cheque(
            db, cheque_nuevo, payload.vuelto_modo, diferencia, fecha
        )

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc

    db.refresh(cheque_nuevo)
    for deuda in afectadas:
        db.refresh(deuda)

    return DeudaSimpleCobroClienteChequeResponse(
        deudas_afectadas=[DeudaSimpleRead.model_validate(d) for d in afectadas],
        cheque_ingresado=ChequeRead.model_validate(cheque_nuevo),
        imputado=reduccion,
        canceladas=canceladas,
        saldo_restante=(saldo_total - reduccion).quantize(Decimal("0.01")),
        vuelto_ars=diferencia,
        vuelto_modo=payload.vuelto_modo if diferencia > Decimal("0.00") else None,
    )


def cobrar_con_cheque(
    db: Session,
    deuda_id: uuid.UUID,
    payload: DeudaSimpleCobrarConChequeRequest,
    created_at: datetime | None = None,
) -> DeudaSimpleCobrarConChequeResponse:
    """Cobra una deuda libre recibiendo un cheque del cliente en vez de efectivo.

    El cheque entra a cartera EN_CARTERA a nombre del cliente de la deuda y salda
    por su **valor neto** (`monto × (1 − %compra)`), no por su nominal.

    **No asienta caja**: no entró efectivo. La plata se reconoce recién cuando ese
    cheque se venda o se cobre, igual que en los fiados (§2) y en el cobro de
    cuotas con cheque (§3). Por eso tampoco lleva `referencia_tipo` de cobro.

    Los cheques son siempre en pesos: si la deuda es en USD, el cobro cruza
    monedas y la `cotizacion` imputa cuánto del saldo (en USD) queda saldado.

    **Si el cheque cubre de más, el excedente se resuelve, no se informa y
    listo**: `vuelto_modo` es obligatorio y va por el mismo camino que el cobro
    por cliente y que el vuelto de un pasivo (§5) — o se le paga en efectivo
    (egreso `VUELTO_PASIVO`, lo único que mueve la caja acá) o el negocio le
    queda debiendo y se crea un pasivo a su favor.
    """
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    if deuda.estado == DeudaSimpleEstado.CANCELADA:
        raise ConflictError("La deuda ya está cancelada.")

    # Solo choca contra cheques vivos: uno anulado libera su número (migración 0017).
    ya_existe = db.scalar(
        select(Cheque).where(
            Cheque.nro_cheque == payload.nro_cheque_pago,
            Cheque.banco == payload.banco_pago,
            Cheque.anulado_at.is_(None),
        )
    )
    if ya_existe is not None:
        banco_txt = f" del banco {payload.banco_pago}" if payload.banco_pago else ""
        raise ConflictError(
            f"Ya existe un cheque Nº '{payload.nro_cheque_pago}'{banco_txt}."
        )

    valor_neto = (
        payload.monto_cheque
        * (_CIEN - payload.porcentaje_compra_cheque)
        / _CIEN
    ).quantize(Decimal("0.01"))

    # El cheque vale pesos; si la deuda es en USD hay que convertir para saber
    # cuánto del saldo salda. `calcular_imputacion_y_vuelto` usa
    # `convertir_a_moneda_deuda` y NO `calcular_reduccion_saldo`, que rechaza un
    # pago mayor al saldo: correcto en efectivo, pero acá el valor del cheque es
    # fijo y un cheque "de más" es el caso normal, no un error.
    equivalente = convertir_a_moneda_deuda(
        deuda.moneda, Moneda.ARS, valor_neto, payload.cotizacion
    )
    es_cross = deuda.moneda != Moneda.ARS

    # Diferencia en la moneda de la deuda: > 0 el negocio le queda debiendo al
    # cliente; < 0 el cliente todavía debe el resto. Es dato informativo.
    diferencia = (equivalente - deuda.saldo_pendiente).quantize(Decimal("0.01"))

    # `vuelto_ars` es el excedente llevado a pesos: es lo que efectivamente se le
    # devuelve o se le queda debiendo, y va en la misma moneda del cheque.
    reduccion, vuelto_ars = calcular_imputacion_y_vuelto(
        deuda.moneda, deuda.saldo_pendiente, valor_neto, payload.cotizacion
    )
    if vuelto_ars > Decimal("0.00") and payload.vuelto_modo is None:
        raise ValidationError(
            f"El cheque cubre toda la deuda y sobran ${vuelto_ars}. Indicá qué "
            "hacer con el vuelto: pagarlo en efectivo o quedar debiéndolo."
        )

    fecha = payload.fecha_cobro or hoy_local()
    cheque_nuevo = Cheque(
        nro_cheque=payload.nro_cheque_pago,
        banco=payload.banco_pago,
        monto=payload.monto_cheque,
        porcentaje_compra=payload.porcentaje_compra_cheque,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        estado=ChequeEstado.EN_CARTERA,
        ganancia=Decimal("0.00"),
        cliente_origen_id=deuda.cliente_id,
    )
    # Se inserta con db.add() y no con create_cheque(): recibir un cheque como
    # pago NO es comprarlo, así que no corresponde el egreso COMPRA_CHEQUE. Mismo
    # criterio que fiados (§2) y que el cobro de cuotas con cheque (§3).
    if created_at is not None:
        cheque_nuevo.created_at = created_at

    deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, reduccion)
    if cancelada:
        deuda.estado = DeudaSimpleEstado.CANCELADA
        deuda.fecha_cancelacion = fecha

    if es_cross and deuda.cotizacion_pago is None:
        deuda.cotizacion_pago = payload.cotizacion

    try:
        db.add(cheque_nuevo)
        # El vuelto referencia al cheque, así que necesita su id antes del commit.
        db.flush()
        if vuelto_ars > Decimal("0.00"):
            svc_pasivos.aplicar_vuelto_cheque(
                db, cheque_nuevo, payload.vuelto_modo, vuelto_ars, fecha
            )
        db.commit()
        db.refresh(deuda)
        db.refresh(cheque_nuevo)
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc

    return DeudaSimpleCobrarConChequeResponse(
        deuda=DeudaSimpleRead.model_validate(deuda),
        cheque_ingresado=ChequeRead.model_validate(cheque_nuevo),
        diferencia=diferencia,
        vuelto_ars=vuelto_ars,
        vuelto_modo=payload.vuelto_modo if vuelto_ars > Decimal("0.00") else None,
    )
