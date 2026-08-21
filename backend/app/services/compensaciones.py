"""compensaciones.py — Saldar la deuda de un cliente contra una del negocio.

Régimen definido 2026-08-21. El negocio le compró algo a Y y le quedó debiendo
(§Comprar sin abonar); X, por su lado, le debe al negocio. En vez de que X pague
y el negocio después le pague a Y, **X le transfiere directo a Y**: bajan las
dos deudas y por la caja del negocio no pasa un peso.

**No asienta ninguna línea en el libro de caja, y esa es toda la gracia.** La
plata nunca entró ni salió de acá. Es el mismo criterio con el que un cobro con
cheque no mueve caja (§2.b): lo que no pasó por el cajón no puede sumar ni
restar en el reporte del día.

Esto se puede seguir cargando como dos operaciones sueltas —cobrarle a X y
pagarle a Y—, y sigue funcionando igual que siempre. Pero esas dos dejan en el
libro un INGRESO y un EGRESO que no existieron: el neto del día da igual, pero
el reporte muestra plata moviéndose que nadie tocó. Y si el operador carga solo
la mitad —cobra y se olvida de pagar—, la caja queda descuadrada de verdad y el
pasivo sigue vivo. Esta operación hace en un paso lo que ahí son dos que hay que
acordarse de completar.

**Quién imputa.** Del lado del cliente, los mismos helpers del cobro consolidado
(§2.c): `svc_deudores` arma la cuota común y cada módulo imputa lo suyo. No se
duplica acá ninguna regla de negocio — duplicarlas es exactamente lo que haría
divergir la compensación del cobro normal.

**FIFO de los dos lados.** Ni el cliente ni el acreedor son "una deuda": al
cliente se le imputa cruzando fiados, deudas libres y préstamos, y al acreedor
se le imputa entre **todas** las deudas que el negocio le tiene, de la más vieja
a la más nueva. Le comprás tres veces a Pedro sin pagarle y son tres pasivos;
cuando alguien le transfiere, esa plata no va contra uno elegido a dedo — llena
el más viejo primero, como todo lo demás en el sistema.

**Los dos lados no se topean igual.** Contra el acreedor, transferir de más está
mal: si X le manda a Y más de lo que el negocio le debe **en total**, Y le pasa a
deber al negocio, y eso es otra operación —se rechaza—. Contra el cliente sí
puede sobrar: X paga lo que tiene, y el excedente le queda a favor como pasivo
del negocio con él, igual que el vuelto de un cheque (§5).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import (
    Compensacion,
    CompensacionImputacion,
    Cuota,
    CuotaEstado,
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    Moneda,
    Pasivo,
    PasivoEstado,
    Prestamo,
    PrestamoEstado,
)
from app.schemas.compensaciones import CompensacionCreate, CompensacionResponse
from app.schemas.deudores import RenglonImputado
from app.services import deudores as svc_deudores
from app.services.conversion import (
    calcular_reduccion_saldo,
    convertir_a_moneda_deuda,
)
from app.services.deudas_simples import repartir_cobro_fifo
from app.services.prestamos import repartir_pago_en_cuotas
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CERO = Decimal("0.00")
_CENTAVO = Decimal("0.01")


# ══════════════════════════════════════════════════════════════════════
#  Medir el efecto real de la imputación
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _Foto:
    """Saldo de un renglón antes de imputarle la compensación.

    Se compara contra el saldo de después para saber **cuánto le tocó de
    verdad**. Medir el efecto en vez de predecirlo evita duplicar acá el reparto
    de cada módulo (que dentro de un préstamo llega hasta la cuota), y deja el
    detalle exacto que la reversión necesita para devolver lo mismo que sacó.
    """

    tipo: str
    # Saldo por sub-entidad: {id: saldo}. Para fiado y deuda libre es una sola
    # entrada (la propia deuda); para un préstamo, una por cuota viva.
    saldos: dict[uuid.UUID, Decimal]


def _foto(renglon: svc_deudores.Renglon) -> _Foto:
    obj = renglon.obj
    if renglon.tipo == "prestamo":
        return _Foto(
            tipo="cuota",
            saldos={
                c.id: (c.monto - (c.monto_pagado or _CERO)).quantize(_CENTAVO)
                for c in obj.cuotas_detalle
                if c.estado != CuotaEstado.COBRADA
            },
        )
    return _Foto(tipo=renglon.tipo, saldos={obj.id: obj.saldo_pendiente})


def _imputaciones_reales(
    renglon: svc_deudores.Renglon, foto: _Foto
) -> list[tuple[str, uuid.UUID, Decimal, bool]]:
    """(tipo, id, monto, cancelo) de cada sub-entidad que efectivamente bajó."""
    obj = renglon.obj
    salida: list[tuple[str, uuid.UUID, Decimal, bool]] = []

    if renglon.tipo == "prestamo":
        for cuota in obj.cuotas_detalle:
            antes = foto.saldos.get(cuota.id)
            if antes is None:
                continue  # ya estaba cobrada antes de esta compensación
            ahora = (cuota.monto - (cuota.monto_pagado or _CERO)).quantize(_CENTAVO)
            delta = (antes - ahora).quantize(_CENTAVO)
            if delta > _CERO:
                salida.append(("cuota", cuota.id, delta, cuota.estado == CuotaEstado.COBRADA))
        return salida

    antes = foto.saldos[obj.id]
    delta = (antes - obj.saldo_pendiente).quantize(_CENTAVO)
    if delta > _CERO:
        salida.append((renglon.tipo, obj.id, delta, obj.saldo_pendiente <= _CERO))
    return salida


# ══════════════════════════════════════════════════════════════════════
#  Registrar la compensación
# ══════════════════════════════════════════════════════════════════════

def cargar_pasivos_acreedor(
    db: Session, acreedor: str, moneda: Moneda, *, bloquear: bool = False
) -> list[Pasivo]:
    """Las deudas vivas del negocio con un acreedor, de la más vieja a la más nueva.

    El orden es por `created_at`: un pasivo no tiene fecha de origen propia más
    allá de cuándo se cargó, y el vencimiento no sirve para esto —una deuda que
    vence antes no es más vieja—. Es el mismo criterio de "primero lo más viejo"
    que usa la imputación del lado del cliente (§2.c).

    El match del nombre es **exacto** (case-insensitive): quién resuelve un
    nombre parcial es quien llama —el bot, con su desambiguación— y acá elegir
    de más significaría saldarle la deuda a otro.
    """
    stmt = (
        select(Pasivo)
        .where(
            func.lower(Pasivo.acreedor) == acreedor.strip().lower(),
            Pasivo.moneda == moneda,
            Pasivo.estado == PasivoEstado.PENDIENTE,
            Pasivo.saldo_pendiente > _CERO,
            Pasivo.anulado_at.is_(None),
        )
        .order_by(Pasivo.created_at.asc())
    )
    if bloquear:
        stmt = stmt.with_for_update()
    return list(db.scalars(stmt))


def compensar(db: Session, payload: CompensacionCreate) -> CompensacionResponse:
    """El cliente le transfiere a un acreedor del negocio y bajan las dos deudas.

    Todo en una transacción: o se mueven los dos lados o no se mueve ninguno.
    Media compensación —el cliente saldado y el acreedor intacto— es justamente
    el descuadre que esta operación viene a evitar.
    """
    cliente = svc_deudores.cliente_o_error(db, payload.cliente_id)
    cliente_id, cliente_nombre = cliente.id, cliente.nombre

    acreedor = payload.acreedor.strip()
    pasivos = cargar_pasivos_acreedor(
        db, acreedor, payload.moneda_pasivo, bloquear=True
    )
    if not pasivos:
        raise ConflictError(
            f"No le debés nada a {acreedor} en {payload.moneda_pasivo.value}: "
            "no hay contra qué compensar."
        )
    saldo_acreedor = sum((p.saldo_pendiente for p in pasivos), _CERO).quantize(_CENTAVO)

    renglones = svc_deudores.cargar_renglones(
        db, cliente_id, payload.moneda_deuda, bloquear=True
    )
    if not renglones:
        raise ConflictError(
            f"{cliente_nombre} no tiene deuda abierta en {payload.moneda_deuda.value}."
        )

    saldo_total = sum((r.saldo for r in renglones), _CERO).quantize(_CENTAVO)

    # Lado del acreedor: transferirle más de lo que el negocio le debe lo dejaría
    # a él debiéndole al negocio, que es otra operación. `calcular_reduccion_saldo`
    # valida la cotización y rechaza el exceso; el mensaje se reescribe porque el
    # suyo habla de "el pago" y acá el que pagó no fue el negocio.
    try:
        imputado_pasivo = calcular_reduccion_saldo(
            payload.moneda_pasivo,
            saldo_acreedor,
            payload.moneda,
            payload.monto,
            payload.cotizacion,
        )
    except ValidationError as exc:
        if "supera el saldo" not in str(exc):
            raise
        cuantas = f" (sumando sus {len(pasivos)} deudas)" if len(pasivos) > 1 else ""
        raise ValidationError(
            f"{cliente_nombre} le habría transferido más de lo que le debés a "
            f"{acreedor}: {saldo_acreedor} {payload.moneda_pasivo.value} de "
            f"saldo{cuantas}. Si le transfirió de más, esa diferencia es otra "
            "operación: cargala aparte."
        ) from exc

    # Lado del cliente: acá sí puede sobrar —paga lo que tiene—, así que se
    # convierte sin topear y el excedente se resuelve aparte.
    convertido = convertir_a_moneda_deuda(
        payload.moneda_deuda, payload.moneda, payload.monto, payload.cotizacion
    )
    imputado_cliente = min(convertido, saldo_total).quantize(_CENTAVO)
    sobra_en_deuda = (convertido - imputado_cliente).quantize(_CENTAVO)
    # El excedente se devuelve en la moneda que se transfirió: esa es la plata
    # real que se movió, igual que el vuelto de un cheque va en pesos porque el
    # cheque es un instrumento en pesos (§2.b).
    excedente = (
        convertir_a_moneda_deuda(
            payload.moneda, payload.moneda_deuda, sobra_en_deuda, payload.cotizacion
        )
        if sobra_en_deuda > _CERO
        else _CERO
    )

    fecha = payload.fecha or hoy_local()
    es_cross_deuda = payload.moneda != payload.moneda_deuda
    cotiz_deuda = payload.cotizacion if es_cross_deuda else None

    compensacion = Compensacion(
        fecha=fecha,
        cliente_id=cliente_id,
        acreedor=acreedor,
        moneda_pasivo=payload.moneda_pasivo,
        moneda=payload.moneda,
        monto=payload.monto,
        moneda_deuda=payload.moneda_deuda,
        cotizacion=payload.cotizacion,
        imputado_cliente=imputado_cliente,
        imputado_pasivo=imputado_pasivo,
        excedente=excedente,
        observaciones=payload.observaciones,
    )
    db.add(compensacion)
    db.flush()  # necesita id para colgarle las imputaciones

    # El reparto no mueve caja: el segundo elemento (el efectivo por renglón) va
    # en cero a propósito. La plata la recibió el acreedor, no el negocio.
    repartido = repartir_cobro_fifo(
        [r.saldo for r in renglones], imputado_cliente, _CERO
    )

    afectados: list[RenglonImputado] = []
    for renglon, (imputa, _sin_caja) in zip(renglones, repartido):
        if imputa <= _CERO:
            continue
        foto = _foto(renglon)
        afectados.append(
            svc_deudores.imputar_renglon(
                db,
                renglon,
                cliente_nombre=cliente_nombre,
                imputado=imputa,
                fecha=fecha,
                monto_caja=None,  # no hay caja: la plata fue al acreedor
                moneda_pago=payload.moneda,
                cotizacion=cotiz_deuda,
            )
        )
        for tipo, entidad_id, monto, cancelo in _imputaciones_reales(renglon, foto):
            db.add(
                CompensacionImputacion(
                    compensacion_id=compensacion.id,
                    entidad_tipo=tipo,
                    entidad_id=entidad_id,
                    monto=monto,
                    cancelo=cancelo,
                )
            )

    # Lado del acreedor: se reparte entre sus deudas de la más vieja a la más
    # nueva, llenando cada una, y sin línea de caja (no salió plata de acá).
    # Es el mismo criterio que del lado del cliente: la plata no va contra una
    # deuda elegida a dedo.
    reparto_pasivos = repartir_pago_en_cuotas(
        [p.saldo_pendiente for p in pasivos], imputado_pasivo
    )
    pasivos_cancelados = 0
    for pas, aplica in zip(pasivos, reparto_pasivos):
        if aplica <= _CERO:
            continue
        pas.saldo_pendiente = (pas.saldo_pendiente - aplica).quantize(_CENTAVO)
        cancelo = pas.saldo_pendiente <= _CERO
        if cancelo:
            pas.saldo_pendiente = _CERO
            pas.estado = PasivoEstado.CANCELADA
            pas.fecha_cancelacion = fecha
            pasivos_cancelados += 1
        # La primera cotización cross-moneda queda de default editable, igual que
        # en un pago normal del pasivo (§5).
        if payload.moneda != pas.moneda and pas.cotizacion_pago is None:
            pas.cotizacion_pago = payload.cotizacion
        db.add(
            CompensacionImputacion(
                compensacion_id=compensacion.id,
                entidad_tipo="pasivo",
                entidad_id=pas.id,
                monto=aplica,
                cancelo=cancelo,
            )
        )

    if excedente > _CERO:
        # Transfirió de más: le queda a favor. Mismo mecanismo que el vuelto de un
        # cheque cuando cubre de más, y sin mover caja — el negocio no le devolvió
        # nada todavía, se lo debe.
        a_favor = Pasivo(
            acreedor=cliente_nombre,
            concepto=f"A favor por transferencia a {acreedor}",
            monto=excedente,
            saldo_pendiente=excedente,
            moneda=payload.moneda,
            estado=PasivoEstado.PENDIENTE,
            origen_tipo="compensacion",
            origen_id=compensacion.id,
        )
        db.add(a_favor)
        db.flush()
        compensacion.pasivo_excedente_id = a_favor.id

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar la compensación.") from exc

    db.refresh(compensacion)

    return CompensacionResponse(
        id=compensacion.id,
        fecha=fecha,
        cliente_id=cliente_id,
        cliente_nombre=cliente_nombre,
        acreedor=acreedor,
        moneda=payload.moneda,
        monto=payload.monto,
        moneda_deuda=payload.moneda_deuda,
        moneda_pasivo=payload.moneda_pasivo,
        renglones=afectados,
        imputado_cliente=imputado_cliente,
        canceladas=sum(1 for r in afectados if r.cancelado),
        saldo_restante_cliente=(saldo_total - imputado_cliente).quantize(_CENTAVO),
        imputado_pasivo=imputado_pasivo,
        saldo_restante_pasivo=(saldo_acreedor - imputado_pasivo).quantize(_CENTAVO),
        pasivos_cancelados=pasivos_cancelados,
        excedente=excedente,
        pasivo_excedente_id=compensacion.pasivo_excedente_id,
    )


# ══════════════════════════════════════════════════════════════════════
#  Lectura
# ══════════════════════════════════════════════════════════════════════

def get_compensacion(db: Session, compensacion_id: uuid.UUID) -> Compensacion:
    comp = db.get(Compensacion, compensacion_id)
    if comp is None or comp.anulado_at is not None:
        raise NotFoundError("Compensación no encontrada.")
    return comp


def list_compensaciones(
    db: Session, cliente_id: uuid.UUID | None = None, acreedor: str | None = None
) -> list[Compensacion]:
    stmt = select(Compensacion).where(Compensacion.anulado_at.is_(None))
    if cliente_id is not None:
        stmt = stmt.where(Compensacion.cliente_id == cliente_id)
    if acreedor is not None:
        stmt = stmt.where(func.lower(Compensacion.acreedor) == acreedor.strip().lower())
    return list(db.scalars(stmt.order_by(Compensacion.created_at.desc())))


# ══════════════════════════════════════════════════════════════════════
#  Reversión
# ══════════════════════════════════════════════════════════════════════

def _devolver_a_renglon(db: Session, imp: CompensacionImputacion) -> str:
    """Le devuelve a un renglón lo que esta compensación le sacó.

    Devuelve el monto exacto que se imputó, no un recálculo: entre medio el
    cliente pudo recibir otros cobros, y rehacer el reparto daría distinto.
    """
    if imp.entidad_tipo == "cuota":
        cuota = db.get(Cuota, imp.entidad_id)
        if cuota is None:
            raise ConflictError("Falta una cuota alcanzada por la compensación.")
        cuota.monto_pagado = (cuota.monto_pagado - imp.monto).quantize(_CENTAVO)
        if cuota.monto_pagado < _CERO:
            raise ConflictError(
                f"La cuota {cuota.numero_cuota} ya no tiene imputado lo que esta "
                "compensación le puso: revisá si se corrigió a mano."
            )
        if imp.cancelo:
            # Volvió a quedar pendiente: sin esto la cuota sigue COBRADA con
            # saldo, y el préstamo no la vuelve a cobrar nunca.
            cuota.estado = CuotaEstado.PENDIENTE
            cuota.fecha_cobro = None
        prestamo = db.get(Prestamo, cuota.prestamo_id)
        if prestamo is not None and prestamo.estado == PrestamoEstado.CANCELADO:
            prestamo.estado = PrestamoEstado.ACTIVO
        return f"cuota {cuota.numero_cuota}"

    if imp.entidad_tipo == "pasivo":
        pas = db.get(Pasivo, imp.entidad_id)
        if pas is None:
            raise ConflictError("Falta una deuda del negocio que la compensación saldó.")
        pas.saldo_pendiente = (pas.saldo_pendiente + imp.monto).quantize(_CENTAVO)
        if imp.cancelo:
            pas.estado = PasivoEstado.PENDIENTE
            pas.fecha_cancelacion = None
        return f"deuda con {pas.acreedor} ({pas.concepto})"

    if imp.entidad_tipo == "fiado":
        fiado = db.get(Fiado, imp.entidad_id)
        if fiado is None:
            raise ConflictError("Falta un fiado alcanzado por la compensación.")
        fiado.saldo_pendiente = (fiado.saldo_pendiente + imp.monto).quantize(_CENTAVO)
        if imp.cancelo:
            fiado.estado = FiadoEstado.ABIERTO
        return f"fiado Nº {fiado.cheque_nro}"

    deuda = db.get(DeudaSimple, imp.entidad_id)
    if deuda is None:
        raise ConflictError("Falta una deuda alcanzada por la compensación.")
    deuda.saldo_pendiente = (deuda.saldo_pendiente + imp.monto).quantize(_CENTAVO)
    if imp.cancelo:
        deuda.estado = DeudaSimpleEstado.ABIERTA
        deuda.fecha_cancelacion = None
    return deuda.concepto


def revertir(
    db: Session,
    compensacion_id: uuid.UUID,
    *,
    operador_id: str,
    motivo: str,
) -> list[str]:
    """Deshace una compensación: las dos deudas vuelven a como estaban.

    Devuelve la descripción de lo que se restituyó, para mostrárselo al operador.

    No hay líneas de caja que revertir —la operación nunca movió la caja—, pero
    sí saldos en los dos lados. A cada uno se le devuelve **exactamente lo que se
    le imputó**, renglón por renglón: las deudas del cliente y las del acreedor
    quedan guardadas igual en `compensacion_imputaciones`, así que restituirlas
    es el mismo recorrido para las dos patas.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador que revierte.")
    if not (motivo and motivo.strip()):
        raise ValidationError("Se requiere un motivo para revertir la compensación.")

    comp = db.scalar(
        select(Compensacion)
        .where(Compensacion.id == compensacion_id)
        .with_for_update()
    )
    if comp is None:
        raise NotFoundError("Compensación no encontrada.")
    if comp.anulado_at is not None:
        raise ConflictError("Esta compensación ya fue revertida.")

    # El excedente que le quedó a favor al cliente: si ya se lo pagaron (o lo usó
    # para otra cosa), revertir dejaría un pago sin nada que lo explique.
    a_favor: Pasivo | None = None
    if comp.pasivo_excedente_id is not None:
        a_favor = db.scalar(
            select(Pasivo)
            .where(Pasivo.id == comp.pasivo_excedente_id)
            .with_for_update()
        )
        if a_favor is not None and a_favor.anulado_at is None:
            if a_favor.saldo_pendiente != a_favor.monto:
                raise ConflictError(
                    "El excedente que le quedó a favor al cliente ya se usó o se "
                    "pagó. Revertí primero ese movimiento."
                )

    restituido: list[str] = []
    try:
        for imp in comp.imputaciones:
            restituido.append(_devolver_a_renglon(db, imp))

        if a_favor is not None and a_favor.anulado_at is None:
            a_favor.anulado_at = datetime.now(tz=UTC)
            a_favor.anulado_por = operador_id.strip()
            a_favor.motivo_anulacion = f"Revertida la compensación: {motivo.strip()}"

        comp.anulado_at = datetime.now(tz=UTC)
        comp.anulado_por = operador_id.strip()
        comp.motivo_anulacion = motivo.strip()

        db.commit()
    except (ConflictError, ValidationError):
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo revertir la compensación.") from exc

    return restituido
