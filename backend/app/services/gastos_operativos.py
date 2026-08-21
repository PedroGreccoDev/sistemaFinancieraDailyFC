from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import CajaCategoria, CajaTipo, GastoOperativo, Moneda
from app.schemas.gastos_operativos import GastoOperativoCreate, GastoOperativoUpdate
from app.services import caja as svc_caja
from app.services import stock_usd as svc_stock
from app.services.exceptions import NotFoundError

_ORIGEN = "gasto"


def _resync_stock_gasto(db: Session, gasto: GastoOperativo) -> None:
    """Rehace la salida de stock de un gasto en dólares (sin commit).

    Un gasto en USD saca dólares del negocio, así que consume lotes FIFO igual
    que cualquier otra salida (§Stock de dólares). En pesos no hay stock que
    tocar, pero igual se barre: un gasto que se corrige de USD a ARS tiene que
    devolver los dólares que había consumido."""
    tenia = svc_stock.listar_por_origen(db, _ORIGEN, gasto.id)
    if not tenia and gasto.moneda != Moneda.USD:
        return

    svc_stock.borrar_por_origen(db, _ORIGEN, gasto.id)
    if gasto.moneda == Moneda.USD:
        svc_stock.egresar(
            db,
            monto=gasto.monto,
            fecha=gasto.fecha_operacion,
            origen_tipo=_ORIGEN,
            origen_id=gasto.id,
            detalle=f"Gasto en dólares — {gasto.concepto}",
        )
    # El SELECT de la reimputación no vería el borrado ni el alta recién hechos:
    # la sesión va con autoflush=False.
    db.flush()
    from app.services.movimientos import _reimputar_fifo

    _reimputar_fifo(db)


def create_gasto(db: Session, payload: GastoOperativoCreate) -> GastoOperativo:
    gasto = GastoOperativo(
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        moneda=payload.moneda,
        fecha_operacion=payload.fecha_operacion or hoy_local(),
        hora_operacion=payload.hora_operacion,
        observaciones=payload.observaciones,
    )
    db.add(gasto)
    db.flush()
    # Un gasto es un egreso de caja en su propia moneda (ARS o USD).
    svc_caja.registrar(
        db,
        fecha=gasto.fecha_operacion,
        moneda=gasto.moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.GASTO,
        monto=gasto.monto,
        referencia_tipo="gasto",
        referencia_id=gasto.id,
        detalle=gasto.concepto,
    )
    _resync_stock_gasto(db, gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


def list_gastos(db: Session) -> list[GastoOperativo]:
    stmt = (
        select(GastoOperativo)
        .where(GastoOperativo.anulado_at.is_(None))
        .order_by(GastoOperativo.fecha_operacion.desc())
    )
    return list(db.scalars(stmt).all())


def _resync_caja_gasto(db: Session, gasto: GastoOperativo) -> None:
    """Reconstruye la línea de caja (egreso) de un gasto tras editar monto/moneda/fecha."""
    svc_caja.borrar_por_referencia(db, "gasto", gasto.id)
    svc_caja.registrar(
        db,
        fecha=gasto.fecha_operacion,
        moneda=gasto.moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.GASTO,
        monto=gasto.monto,
        referencia_tipo="gasto",
        referencia_id=gasto.id,
        detalle=gasto.concepto,
    )


def editar_gasto(
    db: Session, gasto_id: uuid.UUID, payload: GastoOperativoUpdate
) -> GastoOperativo:
    """Corrige la carga de un gasto (panel) y resincroniza su egreso de caja."""
    gasto = db.scalar(
        select(GastoOperativo).where(GastoOperativo.id == gasto_id).with_for_update()
    )
    if gasto is None:
        raise NotFoundError("Gasto no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    if data.get("concepto") is not None:
        gasto.concepto = data["concepto"].strip()
    if data.get("monto") is not None:
        gasto.monto = data["monto"]
    if data.get("moneda") is not None:
        gasto.moneda = data["moneda"]
    if data.get("fecha_operacion") is not None:
        gasto.fecha_operacion = data["fecha_operacion"]
    if "hora_operacion" in data:
        gasto.hora_operacion = data["hora_operacion"]
    if "observaciones" in data:
        gasto.observaciones = data["observaciones"]

    _resync_caja_gasto(db, gasto)
    _resync_stock_gasto(db, gasto)
    db.commit()
    db.refresh(gasto)
    return gasto
