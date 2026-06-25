from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import fecha_local
from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.schemas.movimientos import MovimientoEfectivoCreate, MovimientoEfectivoUpdate
from app.services import caja as svc_caja
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CERO = Decimal("0.00")
_REF = "movimiento_efectivo"


def calcular_ganancia_fifo(
    lotes: list[tuple[Decimal, Decimal]],
    cantidad: Decimal,
    precio_venta: Decimal,
) -> tuple[Decimal, list[Decimal]]:
    """Imputa una venta de divisas contra los lotes de compra en orden FIFO.

    `lotes` es una lista de `(costo_unitario, cantidad_restante)` ya ordenada del
    más viejo al más nuevo. Devuelve `(ganancia_total_ARS, consumos)` donde
    `consumos[i]` es la cantidad de USD tomada del lote i. La ganancia es exacta,
    sin promedios: cada tramo aporta `(precio_venta − costo_lote) × cantidad`.

    Lanza `ValidationError` si el stock total de los lotes no alcanza.
    """
    cantidad = Decimal(cantidad)
    disponible = sum((r for _, r in lotes), _CERO)
    if cantidad > disponible:
        raise ValidationError(
            f"No hay stock de USD suficiente: se intentó vender {cantidad} y "
            f"hay {disponible} en cartera."
        )

    consumos: list[Decimal] = [_CERO] * len(lotes)
    ganancia = _CERO
    pendiente = cantidad
    for i, (costo, restante) in enumerate(lotes):
        if pendiente <= 0:
            break
        tomar = min(restante, pendiente)
        if tomar <= 0:
            continue
        consumos[i] = tomar
        ganancia += (precio_venta - costo) * tomar
        pendiente -= tomar

    return ganancia.quantize(Decimal("0.01")), consumos


def create_movimiento(
    db: Session,
    payload: MovimientoEfectivoCreate,
) -> MovimientoEfectivo:
    fecha_caja = fecha_local(payload.fecha_operacion)
    monto = payload.monto
    cotiz = payload.cotizacion_aplicada
    pesos = (monto * cotiz).quantize(Decimal("0.01"))

    movimiento = MovimientoEfectivo(
        cliente_id=payload.cliente_id,
        tipo=payload.tipo,
        moneda=payload.moneda,
        monto=monto,
        cotizacion_aplicada=cotiz,
        observaciones=payload.observaciones,
    )
    if payload.fecha_operacion is not None:
        movimiento.fecha_operacion = payload.fecha_operacion

    try:
        if payload.tipo == MovimientoEfectivoTipo.COMPRA:
            # La compra incorpora USD al stock a su costo real (lote FIFO).
            movimiento.usd_restante = monto
            movimiento.ganancia = _CERO
            db.add(movimiento)
            db.flush()

            detalle = f"Compra de {monto} USD @ ${cotiz}"
            # Salen pesos de la caja ARS, entran dólares a la caja USD.
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.COMPRA_USD, monto=pesos,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.COMPRA_USD, monto=monto,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
        else:
            # Venta: imputa contra los lotes de compra (FIFO) y realiza la ganancia.
            lotes_rows = list(
                db.scalars(
                    select(MovimientoEfectivo)
                    .where(
                        MovimientoEfectivo.tipo == MovimientoEfectivoTipo.COMPRA,
                        MovimientoEfectivo.usd_restante > 0,
                    )
                    .order_by(
                        MovimientoEfectivo.fecha_operacion.asc(),
                        MovimientoEfectivo.created_at.asc(),
                    )
                    .with_for_update()
                )
            )
            lotes = [(r.cotizacion_aplicada, r.usd_restante) for r in lotes_rows]
            ganancia, consumos = calcular_ganancia_fifo(lotes, monto, cotiz)
            for row, consumo in zip(lotes_rows, consumos):
                if consumo > 0:
                    row.usd_restante = (row.usd_restante - consumo).quantize(Decimal("0.01"))

            movimiento.usd_restante = _CERO
            movimiento.ganancia = ganancia
            db.add(movimiento)
            db.flush()

            detalle = f"Venta de {monto} USD @ ${cotiz}"
            # Entran pesos a la caja ARS, salen dólares de la caja USD.
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.VENTA_USD, monto=pesos, ganancia=ganancia,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.VENTA_USD, monto=monto,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )

        db.commit()
        db.refresh(movimiento)
        return movimiento
    except ValidationError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el movimiento de efectivo.") from exc


def list_movimientos(db: Session) -> list[MovimientoEfectivo]:
    return list(
        db.scalars(select(MovimientoEfectivo).order_by(MovimientoEfectivo.created_at.desc()))
    )


def get_movimiento(db: Session, movimiento_id: uuid.UUID) -> MovimientoEfectivo:
    mov = db.get(MovimientoEfectivo, movimiento_id)
    if mov is None:
        raise NotFoundError("Movimiento de efectivo no encontrado.")
    return mov


def _reimputar_fifo(db: Session) -> None:
    """Recalcula toda la cadena FIFO de divisas desde cero (sin commit).

    Resetea el stock de cada lote (`usd_restante = monto`) y vuelve a imputar las
    ventas en orden cronológico, recomputando su ganancia. Es la forma robusta de
    reflejar una edición sin arrastrar el estado previo. Como editar solo se
    permite sobre lotes intactos y la última venta, esto reproduce idénticamente el
    resto de las operaciones y solo cambia la editada."""
    movs = list(
        db.scalars(
            select(MovimientoEfectivo)
            .order_by(
                MovimientoEfectivo.fecha_operacion.asc(),
                MovimientoEfectivo.created_at.asc(),
            )
            .with_for_update()
        )
    )
    for m in movs:
        if m.tipo == MovimientoEfectivoTipo.COMPRA:
            m.usd_restante = m.monto
    for venta in movs:
        if venta.tipo != MovimientoEfectivoTipo.VENTA:
            continue
        lotes_rows = [
            c
            for c in movs
            if c.tipo == MovimientoEfectivoTipo.COMPRA and c.usd_restante > 0
        ]
        lotes = [(c.cotizacion_aplicada, c.usd_restante) for c in lotes_rows]
        ganancia, consumos = calcular_ganancia_fifo(
            lotes, venta.monto, venta.cotizacion_aplicada
        )
        for row, consumo in zip(lotes_rows, consumos):
            if consumo > 0:
                row.usd_restante = (row.usd_restante - consumo).quantize(Decimal("0.01"))
        venta.ganancia = ganancia
        venta.usd_restante = _CERO


def _resync_caja_movimiento(db: Session, mov: MovimientoEfectivo) -> None:
    """Reconstruye las dos líneas de caja (ARS + USD) de una operación de divisas."""
    svc_caja.borrar_por_referencia(db, _REF, mov.id)
    fecha_caja = fecha_local(mov.fecha_operacion)
    pesos = (mov.monto * mov.cotizacion_aplicada).quantize(Decimal("0.01"))
    if mov.tipo == MovimientoEfectivoTipo.COMPRA:
        detalle = f"Compra de {mov.monto} USD @ ${mov.cotizacion_aplicada}"
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.COMPRA_USD, monto=pesos,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.INGRESO,
            categoria=CajaCategoria.COMPRA_USD, monto=mov.monto,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
    else:
        detalle = f"Venta de {mov.monto} USD @ ${mov.cotizacion_aplicada}"
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
            categoria=CajaCategoria.VENTA_USD, monto=pesos, ganancia=mov.ganancia,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.VENTA_USD, monto=mov.monto,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )


def editar_movimiento(
    db: Session, movimiento_id: uuid.UUID, payload: MovimientoEfectivoUpdate
) -> MovimientoEfectivo:
    """Corrige una operación de divisas respetando la imputación FIFO.

    `cliente_id`/`observaciones` se editan siempre. `monto`/`cotizacion_aplicada`
    solo si la operación no está "trabada" en la cadena FIFO:
      - COMPRA: el lote debe estar intacto (`usd_restante == monto`).
      - VENTA: debe ser la última (no puede haber ventas posteriores).
    """
    mov = db.scalar(
        select(MovimientoEfectivo).where(MovimientoEfectivo.id == movimiento_id).with_for_update()
    )
    if mov is None:
        raise NotFoundError("Movimiento de efectivo no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "cotizacion_aplicada" in data

    if cambia_dinero:
        if mov.tipo == MovimientoEfectivoTipo.COMPRA:
            if mov.usd_restante != mov.monto:
                raise ConflictError(
                    "Esta compra ya fue consumida (total o parcialmente) por una o más "
                    "ventas en la cadena FIFO, así que no se puede editar su monto ni "
                    "cotización. Corregila registrando una operación inversa."
                )
        else:  # VENTA
            posterior = db.scalar(
                select(MovimientoEfectivo.id)
                .where(
                    MovimientoEfectivo.tipo == MovimientoEfectivoTipo.VENTA,
                    MovimientoEfectivo.id != mov.id,
                    tuple_(MovimientoEfectivo.fecha_operacion, MovimientoEfectivo.created_at)
                    > (mov.fecha_operacion, mov.created_at),
                )
                .limit(1)
            )
            if posterior is not None:
                raise ConflictError(
                    "Hay ventas posteriores que dependen de esta imputación FIFO; "
                    "solo se puede editar la última venta. Corregila con una operación "
                    "inversa o editá primero las ventas más nuevas."
                )

    if "cliente_id" in data:
        mov.cliente_id = data["cliente_id"]
    if "observaciones" in data:
        mov.observaciones = data["observaciones"]
    if "monto" in data:
        mov.monto = data["monto"]
    if "cotizacion_aplicada" in data:
        mov.cotizacion_aplicada = data["cotizacion_aplicada"]

    try:
        if mov.tipo == MovimientoEfectivoTipo.COMPRA:
            # Lote intacto: su stock disponible es su monto completo.
            mov.usd_restante = mov.monto
        # Recalcular la cadena (recompone ganancia de la venta editada y stock de lotes).
        _reimputar_fifo(db)
        _resync_caja_movimiento(db, mov)
        db.commit()
        db.refresh(mov)
        return mov
    except (ValidationError, ConflictError):
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el movimiento de efectivo.") from exc
