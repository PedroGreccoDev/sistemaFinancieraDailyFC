from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import DeudaEstado, DeudaTipo
from app.db.session import get_db
from app.schemas.deudas import DeudaCancelarRequest, DeudaCreate, DeudaRead
from app.services import deudas as service

router = APIRouter(prefix="/deudas", tags=["deudas"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=DeudaRead, status_code=201)
def create_deuda(payload: DeudaCreate, db: DbSession) -> DeudaRead:
    return service.create_deuda(db, payload)


@router.get("", response_model=list[DeudaRead])
def list_deudas(
    db: DbSession,
    estado: DeudaEstado | None = None,
    tipo: DeudaTipo | None = None,
) -> list[DeudaRead]:
    return service.list_deudas(db, estado=estado, tipo=tipo)


@router.get("/{deuda_id}", response_model=DeudaRead)
def get_deuda(deuda_id: UUID, db: DbSession) -> DeudaRead:
    return service.get_deuda(db, deuda_id)


@router.post("/{deuda_id}/cancelar", response_model=DeudaRead)
def cancelar_deuda(
    deuda_id: UUID,
    payload: DeudaCancelarRequest,
    db: DbSession,
) -> DeudaRead:
    return service.cancelar_deuda(db, deuda_id, payload)
