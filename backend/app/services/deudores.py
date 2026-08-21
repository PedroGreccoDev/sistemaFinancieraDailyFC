"""deudores.py — Cobro consolidado de la deuda de un cliente.

Un cliente puede deberle al negocio por tres caminos a la vez: un cheque que se
le fió (§2), una deuda libre (§2.b) y las cuotas de un préstamo (§3). Cuando
entrega plata **no está pagando una de esas**: está pagando lo que debe. Este
servicio es esa operación — una sola cuota común sobre las tres fuentes.

**Cómo se imputa.** De la operación **más vieja a la más nueva** por su fecha de
origen (`fecha_fiado`, `fecha` de la deuda libre, `fecha_inicio` del préstamo),
cruzando tipos: si el renglón más viejo es un fiado y el siguiente un préstamo,
primero se llena el fiado. Dentro de un préstamo el importe sigue cayendo en la
cuota más vieja, como en el pago libre de §3.

**Una moneda por vez.** ARS y USD son cajas distintas y no se suman: el cobro
declara `moneda_deuda`. Los cheques fiados son siempre en pesos, así que en USD
solo entran deudas libres y préstamos en dólares. El pago sí puede venir en la
otra moneda con su cotización, igual que en cada módulo por separado.

**Quién asienta la caja.** Cada módulo, con su propia categoría y su propia
referencia: `svc_fiados.imputar_cobro`, `svc_deudas_simples.imputar_cobro` y
`svc_prestamos.imputar_pago`. Ninguno commitea — el commit es de acá, así que
las tres imputaciones y sus líneas de caja entran o no entran juntas. No se
asienta una línea única "cobro al cliente": anular una de esas operaciones borra
sus líneas por referencia, y una línea compartida se llevaría puesta plata de
las otras.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.core.fechas import hoy_local
from app.db.models import (
    Cheque,
    ChequeEstado,
    Cliente,
    CuotaEstado,
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    Moneda,
    Prestamo,
    PrestamoEstado,
)
from app.schemas.cheques import ChequeRead
from app.schemas.deudores import (
    CobroClienteChequeCreate,
    CobroClienteChequeResponse,
    CobroClienteCreate,
    CobroClienteResponse,
    DeudaClienteResumen,
    RenglonImputado,
    RenglonPendiente,
)
from app.services import deudas_simples as svc_deudas_simples
from app.services import fiados as svc_fiados
from app.services import pasivos as svc_pasivos
from app.services import prestamos as svc_prestamos
from app.services.conversion import calcular_reduccion_saldo
from app.services.deudas_simples import (
    calcular_imputacion_y_vuelto,
    repartir_cobro_fifo,
)
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CIEN = Decimal("100")
_CERO = Decimal("0.00")

# Orden de desempate entre tipos cuando dos operaciones son del mismo día y no
# hay `created_at` para distinguirlas. No expresa prioridad de negocio —solo
# hace el reparto determinista, para que el mismo cobro imputado dos veces dé
# siempre el mismo resultado.
_ORDEN_TIPO = {"fiado": 0, "deuda_simple": 1, "prestamo": 2}


@dataclass
class Renglon:
    """Una deuda abierta del cliente, lista para recibir parte de un cobro.

    `obj` es el modelo vivo (Fiado / DeudaSimple / Prestamo): la imputación se
    delega al servicio de su módulo, que sabe qué categoría de caja le
    corresponde y cuándo queda cancelada.
    """

    tipo: str
    id: uuid.UUID
    fecha: date
    saldo: Decimal
    detalle: str
    obj: object
    created_at: datetime | None = None


def saldo_prestamo(prestamo: Prestamo) -> Decimal:
    """Lo que falta cobrar de un préstamo: la suma del saldo de sus cuotas vivas.

    Pura (sin BD): testeable en el estilo de `tests/`."""
    return sum(
        (
            (c.monto - (c.monto_pagado or _CERO))
            for c in prestamo.cuotas_detalle
            if c.estado != CuotaEstado.COBRADA
        ),
        _CERO,
    ).quantize(Decimal("0.01"))


def _detalle_prestamo(prestamo: Prestamo) -> str:
    pendientes = sum(
        1 for c in prestamo.cuotas_detalle if c.estado != CuotaEstado.COBRADA
    )
    plural = "s" if prestamo.cuotas > 1 else ""
    return f"Préstamo · {pendientes}/{prestamo.cuotas} cuota{plural} pend."


def _ts(valor: datetime | None) -> float:
    """`created_at` como número, para desempatar sin comparar fechas con y sin zona.

    Un modelo recién instanciado en memoria (un test, por ejemplo) todavía no
    tiene `created_at`; comparar ese `None` —o un centinela naive— contra un
    `datetime` con zona de la BD explota. Convertir a timestamp evita las dos
    cosas."""
    return valor.timestamp() if valor is not None else 0.0


def armar_renglones(
    fiados: list[Fiado],
    deudas: list[DeudaSimple],
    prestamos: list[Prestamo],
    moneda: Moneda,
) -> list[Renglon]:
    """Arma la cuota común de un cliente, ordenada de la más vieja a la más nueva.

    Recibe las deudas ya filtradas por cliente y estado, y devuelve solo las que
    corresponden a `moneda` y tienen saldo. **Los fiados son siempre en pesos**:
    en un cobro en USD no entran.

    El orden es por fecha de origen; empatan por `created_at` y, si tampoco
    alcanza, por tipo (`_ORDEN_TIPO`). Pura (sin BD): testeable en el estilo de
    `tests/`."""
    renglones: list[Renglon] = []

    if moneda == Moneda.ARS:
        for f in fiados:
            if f.saldo_pendiente <= _CERO:
                continue
            renglones.append(
                Renglon(
                    tipo="fiado",
                    id=f.id,
                    fecha=f.fecha_fiado,
                    saldo=f.saldo_pendiente,
                    detalle=f"Cheque fiado · Nº {f.cheque_nro}",
                    obj=f,
                    created_at=f.created_at,
                )
            )

    for d in deudas:
        if d.moneda != moneda or d.saldo_pendiente <= _CERO:
            continue
        renglones.append(
            Renglon(
                tipo="deuda_simple",
                id=d.id,
                fecha=d.fecha,
                saldo=d.saldo_pendiente,
                detalle=d.concepto,
                obj=d,
                created_at=d.created_at,
            )
        )

    for p in prestamos:
        if p.moneda != moneda:
            continue
        saldo = saldo_prestamo(p)
        if saldo <= _CERO:
            continue
        renglones.append(
            Renglon(
                tipo="prestamo",
                id=p.id,
                fecha=p.fecha_inicio,
                saldo=saldo,
                detalle=_detalle_prestamo(p),
                obj=p,
                created_at=p.created_at,
            )
        )

    renglones.sort(key=lambda r: (r.fecha, _ts(r.created_at), _ORDEN_TIPO[r.tipo]))
    return renglones


def _cargar_renglones(
    db: Session, cliente_id: uuid.UUID, moneda: Moneda, *, bloquear: bool
) -> list[Renglon]:
    """Lee las tres fuentes de deuda del cliente y arma la cuota común.

    Con `bloquear` toma `FOR UPDATE` sobre las filas: dos cobros simultáneos al
    mismo cliente no pueden imputar sobre el mismo saldo. Un módulo nuevo de
    deuda de cliente se da de alta acá y en `armar_renglones`."""
    q_fiados = select(Fiado).where(
        Fiado.cliente_id == cliente_id,
        Fiado.estado == FiadoEstado.ABIERTO,
        Fiado.anulado_at.is_(None),
    )
    q_deudas = select(DeudaSimple).where(
        DeudaSimple.cliente_id == cliente_id,
        DeudaSimple.moneda == moneda,
        DeudaSimple.estado == DeudaSimpleEstado.ABIERTA,
        DeudaSimple.anulado_at.is_(None),
    )
    # ACTIVO o EN_MORA con saldo siguen contando; solo CANCELADO queda afuera.
    q_prestamos = select(Prestamo).where(
        Prestamo.cliente_id == cliente_id,
        Prestamo.moneda == moneda,
        Prestamo.estado != PrestamoEstado.CANCELADO,
        Prestamo.anulado_at.is_(None),
    )
    if bloquear:
        q_fiados = q_fiados.with_for_update()
        q_deudas = q_deudas.with_for_update()
        q_prestamos = q_prestamos.with_for_update()

    fiados = list(db.scalars(q_fiados)) if moneda == Moneda.ARS else []
    deudas = list(db.scalars(q_deudas))
    prestamos = list(db.scalars(q_prestamos.options(selectinload(Prestamo.cuotas_detalle))))

    return armar_renglones(fiados, deudas, prestamos, moneda)


def _cliente_o_error(db: Session, cliente_id: uuid.UUID) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")
    return cliente


def resumen_cliente(
    db: Session, cliente_id: uuid.UUID, moneda: Moneda
) -> DeudaClienteResumen:
    """Cuánto debe un cliente en una moneda, con el detalle que lo compone.

    Lectura sin bloqueo, para contestar por chat o mostrar antes de cobrar."""
    cliente = _cliente_o_error(db, cliente_id)
    renglones = _cargar_renglones(db, cliente_id, moneda, bloquear=False)
    return DeudaClienteResumen(
        cliente_id=cliente.id,
        cliente_nombre=cliente.nombre,
        moneda=moneda,
        total=sum((r.saldo for r in renglones), _CERO).quantize(Decimal("0.01")),
        renglones=[
            RenglonPendiente(
                tipo=r.tipo, id=r.id, detalle=r.detalle, fecha=r.fecha, saldo=r.saldo
            )
            for r in renglones
        ],
    )


def _imputar(
    db: Session,
    renglon: Renglon,
    *,
    cliente_nombre: str,
    imputado: Decimal,
    fecha: date,
    monto_caja: Decimal | None,
    moneda_pago: Moneda,
    cotizacion: Decimal | None,
    cotizacion_stock: Decimal | None = None,
) -> RenglonImputado:
    """Delega la imputación al módulo dueño del renglón y arma su resultado.

    Cada módulo asienta su propia línea de caja (categoría y referencia propias)
    y ninguno commitea: el commit lo da el cobro consolidado."""
    if renglon.tipo == "fiado":
        cancelado = svc_fiados.imputar_cobro(
            db,
            renglon.obj,
            reduccion=imputado,
            fecha=fecha,
            monto_caja=monto_caja,
            moneda_pago=moneda_pago,
            cotizacion=cotizacion,
        )
        restante = renglon.obj.saldo_pendiente
    elif renglon.tipo == "deuda_simple":
        cancelado = svc_deudas_simples.imputar_cobro(
            db,
            renglon.obj,
            cliente_nombre=cliente_nombre,
            imputado=imputado,
            fecha=fecha,
            monto_caja=monto_caja,
            moneda_pago=moneda_pago,
            cotizacion=cotizacion,
            cotizacion_stock=cotizacion_stock,
        )
        restante = renglon.obj.saldo_pendiente
    else:  # prestamo
        cancelado = svc_prestamos.imputar_pago(
            db,
            renglon.obj,
            reduccion=imputado,
            fecha=fecha,
            monto_caja=monto_caja,
            moneda_pago=moneda_pago,
            cotizacion=cotizacion,
            cotizacion_stock=cotizacion_stock,
        )
        restante = saldo_prestamo(renglon.obj)

    return RenglonImputado(
        tipo=renglon.tipo,
        id=renglon.id,
        detalle=renglon.detalle,
        fecha=renglon.fecha,
        imputado=imputado,
        saldo_restante=restante,
        cancelado=cancelado,
    )


# API compartida con `svc_compensaciones`. Una compensación imputa contra la
# deuda del cliente exactamente igual que este cobro —lo único distinto es de
# dónde salió la plata—, así que reusa estos tres en vez de duplicar el reparto:
# duplicarlo es lo que haría divergir la compensación del cobro normal.
cargar_renglones = _cargar_renglones
imputar_renglon = _imputar
cliente_o_error = _cliente_o_error


def cobrar_cliente(
    db: Session, payload: CobroClienteCreate
) -> CobroClienteResponse:
    """Cobra un importe libre contra toda la deuda de un cliente, en efectivo.

    El importe se imputa de la operación más vieja a la más nueva cruzando
    fiados, deudas libres y préstamos. Cada operación alcanzada asienta su
    propia línea de caja en la moneda efectivamente cobrada; el residuo del
    redondeo de un cobro cross-moneda cae en la última alcanzada, para que las
    líneas sumen exactamente lo que entró (ver `repartir_cobro_fifo`)."""
    cliente = _cliente_o_error(db, payload.cliente_id)
    cliente_id, cliente_nombre = cliente.id, cliente.nombre
    renglones = _cargar_renglones(db, cliente_id, payload.moneda_deuda, bloquear=True)
    if not renglones:
        raise ConflictError(
            f"{cliente_nombre} no tiene deuda abierta en {payload.moneda_deuda.value}."
        )

    saldo_total = sum((r.saldo for r in renglones), _CERO).quantize(Decimal("0.01"))
    es_cross = payload.moneda_pago != payload.moneda_deuda
    # Cuánto de la deuda (en su moneda) salda este cobro; valida la cotización y
    # que no se cobre más de lo que el cliente debe.
    reduccion = calcular_reduccion_saldo(
        payload.moneda_deuda,
        saldo_total,
        payload.moneda_pago,
        payload.monto_cobrado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    repartido = repartir_cobro_fifo(
        [r.saldo for r in renglones], reduccion, payload.monto_cobrado
    )
    cotizacion = payload.cotizacion if es_cross else None

    afectados: list[RenglonImputado] = []
    for renglon, (imputa, plata) in zip(renglones, repartido):
        if imputa <= _CERO:
            continue
        afectados.append(
            _imputar(
                db,
                renglon,
                cliente_nombre=cliente_nombre,
                imputado=imputa,
                fecha=fecha,
                monto_caja=plata,
                moneda_pago=payload.moneda_pago,
                cotizacion=cotizacion,
                cotizacion_stock=payload.cotizacion_stock,
            )
        )

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro del cliente.") from exc

    return CobroClienteResponse(
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        moneda_deuda=payload.moneda_deuda,
        renglones=afectados,
        imputado=reduccion,
        canceladas=sum(1 for r in afectados if r.cancelado),
        saldo_restante=(saldo_total - reduccion).quantize(Decimal("0.01")),
    )


def cobrar_cliente_con_cheque(
    db: Session,
    payload: CobroClienteChequeCreate,
    created_at: datetime | None = None,
) -> CobroClienteChequeResponse:
    """Cobra toda la deuda de un cliente con un solo cheque.

    Salda por el **valor neto** del cheque, imputado de la operación más vieja a
    la más nueva igual que el efectivo. **No asienta caja por el cobro**: el
    cheque entra a cartera a nombre del cliente y la plata se reconoce recién al
    venderlo o cobrarlo (mismo criterio que §2, §2.b y §3).

    Un cheque que cubre de más es el caso normal —el cliente entrega el que
    tiene—, así que se convierte con `calcular_imputacion_y_vuelto` (sin topear)
    y el excedente lo resuelve `svc_pasivos.aplicar_vuelto_cheque` (§5): o se le
    devuelve en efectivo —lo único que mueve la caja acá— o queda como pasivo a
    su favor."""
    cliente = _cliente_o_error(db, payload.cliente_id)
    cliente_id, cliente_nombre = cliente.id, cliente.nombre
    renglones = _cargar_renglones(db, cliente_id, payload.moneda_deuda, bloquear=True)
    if not renglones:
        raise ConflictError(
            f"{cliente_nombre} no tiene deuda abierta en {payload.moneda_deuda.value}."
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

    saldo_total = sum((r.saldo for r in renglones), _CERO).quantize(Decimal("0.01"))
    valor_neto = (
        payload.monto_cheque * (_CIEN - payload.porcentaje_compra_cheque) / _CIEN
    ).quantize(Decimal("0.01"))

    es_cross = payload.moneda_deuda != Moneda.ARS
    reduccion, diferencia = calcular_imputacion_y_vuelto(
        payload.moneda_deuda, saldo_total, valor_neto, payload.cotizacion
    )
    if diferencia > _CERO and payload.vuelto_modo is None:
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
        ganancia=_CERO,
        cliente_origen_id=cliente_id,
    )
    if created_at is not None:
        cheque_nuevo.created_at = created_at
    # db.add() y no create_cheque(): recibir un cheque como pago NO es comprarlo,
    # así que no corresponde el egreso COMPRA_CHEQUE.
    db.add(cheque_nuevo)
    db.flush()  # necesita id para la referencia de caja del vuelto

    # El cheque no mueve caja, así que solo se imputan saldos: el segundo
    # elemento del reparto (el efectivo por renglón) no se usa.
    repartido = repartir_cobro_fifo([r.saldo for r in renglones], reduccion, _CERO)
    cotizacion = payload.cotizacion if es_cross else None

    afectados: list[RenglonImputado] = []
    for renglon, (imputa, _sin_caja) in zip(renglones, repartido):
        if imputa <= _CERO:
            continue
        afectados.append(
            _imputar(
                db,
                renglon,
                cliente_nombre=cliente_nombre,
                imputado=imputa,
                fecha=fecha,
                monto_caja=None,  # el cheque no mueve caja: entra a cartera
                moneda_pago=Moneda.ARS,
                cotizacion=cotizacion,
            )
        )

    if diferencia > _CERO:
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

    return CobroClienteChequeResponse(
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        moneda_deuda=payload.moneda_deuda,
        renglones=afectados,
        imputado=reduccion,
        canceladas=sum(1 for r in afectados if r.cancelado),
        saldo_restante=(saldo_total - reduccion).quantize(Decimal("0.01")),
        cheque_ingresado=ChequeRead.model_validate(cheque_nuevo),
        vuelto_ars=diferencia,
        vuelto_modo=payload.vuelto_modo if diferencia > _CERO else None,
    )
