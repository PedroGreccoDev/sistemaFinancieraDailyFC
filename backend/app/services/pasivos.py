from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Pasivo, PasivoEstado
from app.schemas.pasivos import PasivoCancelarRequest, PasivoCreate
from app.services.exceptions import NotFoundError, ConflictError


def create_pasivo(db: Session, payload: PasivoCreate) -> Pasivo:
    pasivo = Pasivo(
        acreedor=payload.acreedor.strip(),
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        moneda=payload.moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=payload.fecha_vencimiento,
        observaciones=payload.observaciones,
    )
    db.add(pasivo)
    db.commit()
    db.refresh(pasivo)
    return pasivo


def get_pasivo(db: Session, pasivo_id: uuid.UUID) -> Pasivo:
    pasivo = db.get(Pasivo, pasivo_id)
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    return pasivo


def list_pasivos(db: Session, estado: PasivoEstado | None = None) -> list[Pasivo]:
    stmt = select(Pasivo)
    if estado is not None:
        stmt = stmt.where(Pasivo.estado == estado)
    stmt = stmt.order_by(Pasivo.fecha_vencimiento.asc().nulls_last(), Pasivo.created_at.desc())
    return list(db.scalars(stmt).all())


def cancelar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarRequest
) -> Pasivo:
    pasivo = get_pasivo(db, pasivo_id)
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError(f"El pasivo ya está cancelado.")
    pasivo.estado = PasivoEstado.CANCELADA
    pasivo.fecha_cancelacion = payload.fecha_cancelacion or date.today()
    db.commit()
    db.refresh(pasivo)
    return pasivo
