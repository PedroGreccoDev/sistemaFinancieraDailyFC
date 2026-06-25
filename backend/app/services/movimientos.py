from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select
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
from app.schemas.movimientos import MovimientoEfectivoCreate
from app.services import caja as svc_caja
from app.services.exceptions import DatabaseWriteError, ValidationError

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
