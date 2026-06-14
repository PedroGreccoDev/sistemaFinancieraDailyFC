from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import GastoOperativo
from app.schemas.gastos_operativos import GastoOperativoCreate


def create_gasto(db: Session, payload: GastoOperativoCreate) -> GastoOperativo:
    gasto = GastoOperativo(
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        moneda=payload.moneda,
        fecha_operacion=payload.fecha_operacion or hoy_local(),
        observaciones=payload.observaciones,
    )
    db.add(gasto)
    db.commit()
    db.refresh(gasto)
    return gasto


def list_gastos(db: Session) -> list[GastoOperativo]:
    stmt = select(GastoOperativo).order_by(GastoOperativo.fecha_operacion.desc())
    return list(db.scalars(stmt).all())
