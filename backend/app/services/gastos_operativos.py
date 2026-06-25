from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import CajaCategoria, CajaTipo, GastoOperativo
from app.schemas.gastos_operativos import GastoOperativoCreate
from app.services import caja as svc_caja


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
    db.commit()
    db.refresh(gasto)
    return gasto


def list_gastos(db: Session) -> list[GastoOperativo]:
    stmt = select(GastoOperativo).order_by(GastoOperativo.fecha_operacion.desc())
    return list(db.scalars(stmt).all())
