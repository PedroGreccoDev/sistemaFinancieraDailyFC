from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import PasivoEstado
from app.db.session import get_db
from app.schemas.pasivos import PasivoCancelarRequest, PasivoCreate, PasivoRead
from app.services import pasivos as service

router = APIRouter(prefix="/pasivos", tags=["pasivos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PasivoRead, status_code=201)
def create_pasivo(payload: PasivoCreate, db: DbSession) -> PasivoRead:
    return service.create_pasivo(db, payload)


@router.get("", response_model=list[PasivoRead])
def list_pasivos(
    db: DbSession,
    estado: PasivoEstado | None = None,
) -> list[PasivoRead]:
    return service.list_pasivos(db, estado=estado)


@router.get("/{pasivo_id}", response_model=PasivoRead)
def get_pasivo(pasivo_id: UUID, db: DbSession) -> PasivoRead:
    return service.get_pasivo(db, pasivo_id)


@router.post("/{pasivo_id}/cancelar", response_model=PasivoRead)
def cancelar_pasivo(
    pasivo_id: UUID,
    payload: PasivoCancelarRequest,
    db: DbSession,
) -> PasivoRead:
    return service.cancelar_pasivo(db, pasivo_id, payload)
