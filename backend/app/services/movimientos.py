from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import MovimientoEfectivo
from app.schemas.movimientos import MovimientoEfectivoCreate
from app.services.exceptions import DatabaseWriteError


def create_movimiento(
    db: Session,
    payload: MovimientoEfectivoCreate,
) -> MovimientoEfectivo:
    movimiento = MovimientoEfectivo(**payload.model_dump())
    try:
        db.add(movimiento)
        db.commit()
        db.refresh(movimiento)
        return movimiento
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el movimiento de efectivo.") from exc


def list_movimientos(db: Session) -> list[MovimientoEfectivo]:
    return list(
        db.scalars(select(MovimientoEfectivo).order_by(MovimientoEfectivo.created_at.desc()))
    )

