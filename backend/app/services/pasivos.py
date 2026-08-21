from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    MedioPago,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
    Pasivo,
    PasivoEstado,
)
from app.core.fechas import fecha_local, hoy_local
from app.services import caja as svc_caja
from app.services.conversion import calcular_reduccion_saldo
from app.schemas.pasivos import (
    PasivoCancelarConChequeRequest,
    PasivoCreate,
    PasivoPagoRequest,
    PasivoUpdate,
)
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

# calcular_reduccion_saldo se movió a app.services.conversion (lo comparten pasivos,
# fiados y préstamos). Se re-exporta acá por compatibilidad con imports existentes.
__all__ = ["calcular_reduccion_saldo"]

_CERO = Decimal("0.00")

# Campos que forman parte de la línea `INGRESO_PASIVO` del alta: si la edición toca
# alguno, esa línea se rehace (monto, moneda y fecha son la línea misma; acreedor y
# concepto, su detalle).
_CAMPOS_INGRESO = frozenset(
    {
        "ingreso_caja", "fecha_ingreso", "cotizacion_ingreso_usd",
        "monto", "moneda", "acreedor", "concepto",
    }
)


def create_pasivo(
    db: Session,
    payload: PasivoCreate,
    created_at: datetime | None = None,
) -> Pasivo:
    """Anota una deuda del negocio.

    Por defecto **no mueve la caja**: la deuda típica es comercial —le debo al
    proveedor por la mercadería— y ahí no entró un peso, solo quedó la obligación.
    La caja se toca recién al pagarla (`PAGO_PASIVO`).

    Con `ingreso_caja` es el otro caso: **alguien le prestó plata al negocio**. La
    deuda nace igual, pero además el efectivo entró al cajón, así que el alta
    asienta el INGRESO `INGRESO_PASIVO` de `fecha_ingreso`. Sin eso el reporte del
    día quedaría corto contra la plata real.

    **Si le prestaron dólares, además hace falta el lote de stock**: la caja USD y
    lo que se puede vender son cosas distintas (§4), así que el alta exige la
    cotización con la que entran al FIFO."""
    fecha_ingreso = payload.fecha_ingreso
    if payload.ingreso_caja and fecha_ingreso is None:
        fecha_ingreso = fecha_local(created_at)
    if payload.ingreso_caja:
        _exigir_cotizacion_usd(payload.moneda, payload.cotizacion_ingreso_usd)

    pasivo = Pasivo(
        acreedor=payload.acreedor.strip(),
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        saldo_pendiente=payload.monto,
        moneda=payload.moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=payload.fecha_vencimiento,
        observaciones=payload.observaciones,
        ingreso_caja=payload.ingreso_caja,
        # Se guarda solo si entró plata: una fecha suelta sin ingreso confunde.
        fecha_ingreso=fecha_ingreso if payload.ingreso_caja else None,
        cotizacion_ingreso_usd=(
            payload.cotizacion_ingreso_usd
            if payload.ingreso_caja and payload.moneda == Moneda.USD
            else None
        ),
    )
    if created_at is not None:
        pasivo.created_at = created_at
    db.add(pasivo)
    # El ingreso necesita el id del pasivo para referenciarlo, y sin flush todavía
    # no lo tiene. El commit de abajo persiste deuda y línea de caja juntas.
    db.flush()
    _registrar_ingreso(db, pasivo)
    _crear_lote_usd(db, pasivo)
    db.commit()
    db.refresh(pasivo)
    return pasivo


def _exigir_cotizacion_usd(moneda: Moneda, cotizacion: Decimal | None) -> None:
    """Dólares prestados sin costo declarado no pueden entrar al stock.

    Y sin stock no se pueden vender: el error aparecería recién el día que se
    intente venderlos, cuando ya no se sabe a cuánto estaba el dólar aquel día.
    Mismo criterio que el saldo inicial en USD (§Apertura) y los ajustes (§Ajustes).
    La cotización la dicta el operador; el sistema no la asume nunca."""
    if moneda != Moneda.USD:
        return
    if cotizacion is None or cotizacion <= _CERO:
        raise ValidationError(
            "Decinos a cuánto valuás esos dólares ($/USD): es el costo con el que "
            "entran al stock y contra el que se calcula la ganancia si los vendés."
        )


def _crear_lote_usd(db: Session, pasivo: Pasivo) -> MovimientoEfectivo | None:
    """Crea (sin commit) el lote FIFO de unos dólares que le prestaron al negocio.

    Se inserta directo, sin pasar por `create_movimiento`, para que **no asiente
    caja**: la caja USD ya la mueve la línea `INGRESO_PASIVO`, y una compra además
    restaría pesos que nunca salieron. Mismo criterio que el lote de apertura
    (§Apertura) y el de un ajuste que suma dólares (§Ajustes de caja); comparte con
    ellos la marca `es_ajuste`, que es la de "stock que entró sin una compra
    detrás" —no aparece en el listado de divisas ni asienta caja al resincronizar—.

    El costo es la cotización que declaró el operador: contra eso se calcula la
    ganancia el día que los venda, igual que si los hubiera comprado."""
    if not pasivo.ingreso_caja or pasivo.moneda != Moneda.USD:
        return None
    lote = MovimientoEfectivo(
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=pasivo.monto,
        cotizacion_aplicada=pasivo.cotizacion_ingreso_usd,
        ganancia=_CERO,
        usd_restante=pasivo.monto,  # lote intacto: nada consumido todavía
        fecha_operacion=datetime.combine(
            pasivo.fecha_ingreso or hoy_local(), time.min, tzinfo=UTC
        ),
        observaciones=f"Stock por préstamo recibido de {pasivo.acreedor}",
        es_ajuste=True,
    )
    db.add(lote)
    db.flush()
    pasivo.lote_id = lote.id
    return lote


def _borrar_lote_usd(db: Session, pasivo: Pasivo) -> None:
    """Saca de la cadena el lote de un préstamo en dólares (sin commit).

    Se bloquea si ya se vendió algo de ese lote: quitarlo dejaría esas ventas sin
    el stock del que salieron y reescribiría su ganancia ya reportada. Mismo
    criterio que anular un ajuste en USD (§Ajustes de caja)."""
    if pasivo.lote_id is None:
        return
    lote = db.get(MovimientoEfectivo, pasivo.lote_id)
    # Se valida ANTES de tocar nada: si esto corta a mitad de camino, la deuda no
    # puede quedar sin su vínculo al lote que sigue existiendo.
    if lote is not None and lote.usd_restante != lote.monto:
        consumido = lote.monto - lote.usd_restante
        raise ConflictError(
            f"No se puede cambiar esta deuda: {consumido} de los {lote.monto} USD que "
            "te prestaron ya se vendieron. Anulá primero esas ventas."
        )
    pasivo.lote_id = None
    if lote is not None:
        db.delete(lote)


def _registrar_ingreso(db: Session, pasivo: Pasivo) -> None:
    """Asienta (sin commit) el ingreso de la plata que se tomó prestada.

    No hace nada si la deuda no trajo plata, que es el caso normal."""
    if not pasivo.ingreso_caja:
        return
    svc_caja.registrar(
        db,
        fecha=pasivo.fecha_ingreso or hoy_local(),
        moneda=pasivo.moneda,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.INGRESO_PASIVO,
        monto=pasivo.monto,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=f"Préstamo recibido de {pasivo.acreedor} — {pasivo.concepto}",
    )


def _resync_caja_ingreso(db: Session, pasivo: Pasivo) -> None:
    """Rehace la línea de caja del alta tras editar la deuda (sin commit).

    Barre **solo** la línea `INGRESO_PASIVO`: los `PAGO_PASIVO` de la misma
    referencia son plata que salió de verdad y no se tocan.

    Si el préstamo era en dólares, rehace también su lote de stock: el monto, la
    moneda y la fecha son tanto la línea de caja como el lote."""
    svc_caja.borrar_por_referencia(
        db, "pasivo", pasivo.id, categoria=CajaCategoria.INGRESO_PASIVO
    )
    _registrar_ingreso(db, pasivo)

    # El lote se rehace siempre que había uno o corresponde uno nuevo. Borrar antes
    # de crear: la deuda es una sola y corregirla no debe acumular lotes.
    tenia_lote = pasivo.lote_id is not None
    _borrar_lote_usd(db, pasivo)
    creado = _crear_lote_usd(db, pasivo)
    if tenia_lote or creado is not None:
        # El stock cambió: hay que reimputar la cadena, o las ventas posteriores
        # quedarían apuntando a un lote que ya no existe.
        from app.services.movimientos import _reimputar_fifo

        db.flush()
        _reimputar_fifo(db)


def get_pasivo(db: Session, pasivo_id: uuid.UUID) -> Pasivo:
    pasivo = db.get(Pasivo, pasivo_id)
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    return pasivo


# ══════════════════════════════════════════════════════════════════════
#  Compras a deber: el pasivo que genera la propia compra
# ══════════════════════════════════════════════════════════════════════

def repartir_compra(
    total: Decimal, monto_abonado: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Parte el precio de una compra en (lo que salió de la caja, lo que se debe).

    `monto_abonado` en `None` significa **se pagó todo**: es la compra normal y el
    comportamiento que el sistema tuvo siempre, así que un default distinto
    cambiaría en silencio la caja de todas las compras existentes.

    Pura (sin BD): la comparten la compra de dólares y la de cheques, que solo
    difieren en cómo calculan el total —`monto × cotización` contra el valor neto
    del cheque— y tienen que repartirlo igual."""
    total = total.quantize(Decimal("0.01"))
    if monto_abonado is None:
        return total, _CERO
    abonado = monto_abonado.quantize(Decimal("0.01"))
    if abonado < _CERO:
        raise ValidationError("El monto abonado no puede ser negativo.")
    if abonado > total:
        raise ValidationError(
            f"Abonaste ${abonado} y la compra es de ${total}: el monto abonado no "
            "puede superar el total."
        )
    return abonado, (total - abonado).quantize(Decimal("0.01"))


def crear_por_compra(
    db: Session,
    *,
    acreedor: str,
    concepto: str,
    monto: Decimal,
    moneda: Moneda,
    origen_tipo: str,
    origen_id: uuid.UUID,
    fecha_vencimiento: date | None = None,
) -> Pasivo:
    """Asienta lo que quedó a deber de una compra (dólares o cheque).

    **No commitea**: la persiste el commit de la propia compra, para que la
    compra y su deuda entren o no entren juntas. Es el mismo criterio con el que
    `caja.registrar` asienta el libro.

    No mueve la caja —esa es toda la gracia de comprar a deber: la plata no
    salió—. El egreso lo asienta la compra por lo que sí se abonó, y el resto
    aparecerá el día que se pague este pasivo (o nunca, si se salda compensándolo
    contra un cliente que debe)."""
    pasivo = Pasivo(
        acreedor=acreedor.strip(),
        concepto=concepto.strip(),
        monto=monto,
        saldo_pendiente=monto,
        moneda=moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=fecha_vencimiento,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )
    db.add(pasivo)
    return pasivo


def pasivo_de_origen(
    db: Session, origen_tipo: str, origen_id: uuid.UUID
) -> Pasivo | None:
    """El pasivo vivo que generó una compra, si quedó algo a deber."""
    return db.scalar(
        select(Pasivo).where(
            Pasivo.origen_tipo == origen_tipo,
            Pasivo.origen_id == origen_id,
            Pasivo.anulado_at.is_(None),
        )
    )


def list_pasivos(db: Session, estado: PasivoEstado | None = None) -> list[Pasivo]:
    stmt = select(Pasivo).where(Pasivo.anulado_at.is_(None))
    if estado is not None:
        stmt = stmt.where(Pasivo.estado == estado)
    stmt = stmt.order_by(Pasivo.fecha_vencimiento.asc().nulls_last(), Pasivo.created_at.desc())
    return list(db.scalars(stmt).all())


def editar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoUpdate
) -> Pasivo:
    """Corrige la carga de una deuda (panel).

    `acreedor`, `concepto`, `fecha_vencimiento` y `observaciones` se editan siempre.
    `monto`/`moneda` solo si la deuda está PENDIENTE y sin pagos parciales (cambiarlos
    con pagos hechos desincronizaría la caja); al editar el monto se recalcula el saldo.

    `ingreso_caja`/`fecha_ingreso` corrigen si con la deuda entró plata y qué día:
    sirve tanto para marcar un préstamo que se cargó como deuda común (el ingreso
    aparece) como para desmarcarlo (el ingreso desaparece). Como el monto, la moneda
    y el acreedor son parte de esa línea, cualquiera de ellos la manda a rehacer."""
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "moneda" in data
    tiene_pagos = pasivo.saldo_pendiente != pasivo.monto
    if cambia_dinero and (pasivo.estado == PasivoEstado.CANCELADA or tiene_pagos):
        raise ConflictError(
            "La deuda está cancelada o ya tiene pagos parciales; solo se pueden editar "
            "acreedor, concepto, vencimiento y observaciones."
        )

    if "acreedor" in data:
        pasivo.acreedor = data["acreedor"].strip()
    if "concepto" in data:
        pasivo.concepto = data["concepto"].strip()
    if "fecha_vencimiento" in data:
        pasivo.fecha_vencimiento = data["fecha_vencimiento"]
    if "observaciones" in data:
        pasivo.observaciones = data["observaciones"]
    if "moneda" in data:
        pasivo.moneda = data["moneda"]
    if "monto" in data:
        # Sin pagos parciales (garantizado arriba): el saldo sigue al monto.
        pasivo.monto = data["monto"]
        pasivo.saldo_pendiente = data["monto"]
    if "fecha_ingreso" in data:
        pasivo.fecha_ingreso = data["fecha_ingreso"]
    if "cotizacion_ingreso_usd" in data:
        pasivo.cotizacion_ingreso_usd = data["cotizacion_ingreso_usd"]
    if "ingreso_caja" in data:
        pasivo.ingreso_caja = data["ingreso_caja"]
        if not pasivo.ingreso_caja:
            pasivo.fecha_ingreso = None
    # Marcar que entró plata sin decir qué día: se imputa al día del alta, que es
    # cuando se cargó la deuda. Mejor eso que dejar la línea sin fecha.
    if pasivo.ingreso_caja and pasivo.fecha_ingreso is None:
        pasivo.fecha_ingreso = fecha_local(pasivo.created_at)
    if pasivo.ingreso_caja:
        _exigir_cotizacion_usd(pasivo.moneda, pasivo.cotizacion_ingreso_usd)
    else:
        # Sin ingreso no hay lote, y un costo colgado sin dólares confunde.
        pasivo.cotizacion_ingreso_usd = None

    # Cualquiera de estos campos forma parte de la línea de caja del alta.
    if not _CAMPOS_INGRESO.isdisjoint(data):
        _resync_caja_ingreso(db, pasivo)

    db.commit()
    db.refresh(pasivo)
    return pasivo


def pagar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoPagoRequest
) -> Pasivo:
    """Paga una deuda (total o parcial) en efectivo o transferencia.

    La caja se descuenta en la moneda efectivamente pagada (`moneda_pago`); el
    saldo de la deuda baja por el equivalente en su propia moneda (vía cotización
    si el pago cruza monedas)."""
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")

    es_cross = payload.moneda_pago != pasivo.moneda
    reduccion = calcular_reduccion_saldo(
        pasivo.moneda,
        pasivo.saldo_pendiente,
        payload.moneda_pago,
        payload.monto_pagado,
        payload.cotizacion,
    )

    pasivo.saldo_pendiente = (pasivo.saldo_pendiente - reduccion).quantize(Decimal("0.01"))
    fecha = payload.fecha_cancelacion or hoy_local()
    if pasivo.saldo_pendiente == Decimal("0.00"):
        pasivo.estado = PasivoEstado.CANCELADA
        pasivo.fecha_cancelacion = fecha

    # La primera cotización cross-moneda queda como default editable para próximos pagos.
    if es_cross and pasivo.cotizacion_pago is None:
        pasivo.cotizacion_pago = payload.cotizacion

    detalle = f"Pago deuda a {pasivo.acreedor}"
    if es_cross:
        detalle += f" ({reduccion} {pasivo.moneda.value} @ {payload.cotizacion})"

    # Pagar la deuda saca dinero de la caja en la moneda efectivamente pagada (incluye parciales).
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=payload.moneda_pago,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.PAGO_PASIVO,
        monto=payload.monto_pagado,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=detalle,
        medio_pago=payload.medio_pago,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    db.commit()
    db.refresh(pasivo)
    return pasivo


def cancelar_con_cheque(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarConChequeRequest
) -> Pasivo:
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")

    cheque = db.scalar(
        select(Cheque).where(Cheque.id == payload.cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError(f"Cheque '{payload.cheque_id}' no encontrado.")
    if cheque.estado != ChequeEstado.EN_CARTERA:
        raise ConflictError(
            f"El cheque Nº {cheque.nro_cheque} no está en cartera "
            f"(estado: {cheque.estado.value})."
        )

    valor_neto = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    # diferencia > 0: el cheque cubre de más | diferencia < 0: saldo restante
    diferencia = (valor_neto - pasivo.saldo_pendiente).quantize(Decimal("0.01"))

    # Si el cheque cubre de más, el operador DEBE indicar qué hacer con el vuelto.
    if diferencia > Decimal("0.00") and payload.vuelto_modo is None:
        raise ValidationError(
            "El cheque cubre de más. Indicá qué hacer con el vuelto: "
            "'SALDAR_EFECTIVO' (le pagás la diferencia) o 'QUEDA_DEBIENDO' "
            "(queda como deuda a favor del cliente)."
        )

    fecha_canc = payload.fecha_cancelacion or hoy_local()
    try:
        # Pagar la deuda entregando un cheque de cartera NO mueve efectivo (el desembolso
        # ya ocurrió al comprar el cheque); por eso pasa por el modelo, no por svc_cheques.
        cheque.transition_to(
            ChequeEstado.VENDIDO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
        )
        if diferencia >= Decimal("0.00"):
            pasivo.saldo_pendiente = Decimal("0.00")
            pasivo.estado = PasivoEstado.CANCELADA
            pasivo.fecha_cancelacion = fecha_canc
            if diferencia > Decimal("0.00"):
                aplicar_vuelto_cheque(db, cheque, payload.vuelto_modo, diferencia, fecha_canc)
        else:
            pasivo.saldo_pendiente = (-diferencia).quantize(Decimal("0.01"))

        db.commit()
        db.refresh(pasivo)
        return pasivo
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cancelar la deuda con cheque.") from exc


def aplicar_vuelto_cheque(
    db: Session,
    cheque: Cheque,
    modo: str | None,
    diferencia: Decimal,
    fecha: date,
) -> None:
    """Resuelve el vuelto cuando un cheque cubre de más (diferencia > 0).

    El vuelto es en ARS (el cheque es un instrumento en pesos).

    La usan los dos lados del negocio: pagar un pasivo con un cheque de más
    (§5) y cobrarle a un cliente con un cheque que supera todo lo que debe
    (§2.b). Es la misma situación —el cheque no se puede recortar a medida— y
    tiene que resolverse igual en ambos, por eso vive acá y es pública."""
    cliente = cheque.cliente_origen
    cliente_nombre = cliente.nombre if cliente else "cliente"

    if modo == "SALDAR_EFECTIVO":
        # Le pagás el vuelto en efectivo/transferencia: egreso de caja ARS.
        svc_caja.registrar(
            db,
            fecha=fecha,
            moneda=Moneda.ARS,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.VUELTO_PASIVO,
            monto=diferencia,
            referencia_tipo="cheque",
            referencia_id=cheque.id,
            detalle=f"Vuelto en efectivo a {cliente_nombre} (cheque Nº {cheque.nro_cheque})",
        )
    else:  # QUEDA_DEBIENDO
        # Quedás debiendo: se crea un pasivo a favor del cliente (sin movimiento de caja).
        db.add(
            Pasivo(
                acreedor=cliente_nombre,
                concepto=f"Vuelto cheque Nº {cheque.nro_cheque}",
                monto=diferencia,
                saldo_pendiente=diferencia,
                moneda=Moneda.ARS,
                estado=PasivoEstado.PENDIENTE,
            )
        )
