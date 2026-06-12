from __future__ import annotations

from datetime import date
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Deuda, DeudaEstado, DeudaTipo
from app.schemas.deudas import DeudaCancelarRequest, DeudaCreate
from app.services.exceptions import ConflictError, DatabaseWriteError, NotFoundError


def create_deuda(db: Session, payload: DeudaCreate) -> Deuda:
    deuda = Deuda(**payload.model_dump(), estado=DeudaEstado.PENDIENTE)
    try:
        db.add(deuda)
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear la deuda.") from exc


def get_deuda(db: Session, deuda_id: UUID) -> Deuda:
    deuda = db.get(Deuda, deuda_id)
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    return deuda


def list_deudas(
    db: Session,
    estado: DeudaEstado | None = None,
    tipo: DeudaTipo | None = None,
) -> list[Deuda]:
    query = select(Deuda)
    if estado is not None:
        query = query.where(Deuda.estado == estado)
    if tipo is not None:
        query = query.where(Deuda.tipo == tipo)
    return list(db.scalars(query.order_by(Deuda.created_at.desc())))


def cancelar_deuda(db: Session, deuda_id: UUID, payload: DeudaCancelarRequest) -> Deuda:
    deuda = db.scalar(select(Deuda).where(Deuda.id == deuda_id).with_for_update())
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    if deuda.estado == DeudaEstado.CANCELADA:
        raise ConflictError("La deuda ya está cancelada.")

    deuda.estado = DeudaEstado.CANCELADA
    deuda.fecha_cancelacion = payload.fecha_cancelacion or date.today()

    try:
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cancelar la deuda.") from exc
