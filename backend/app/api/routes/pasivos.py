from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import PasivoEstado
from app.db.session import get_db
from app.schemas.pasivos import (
    PasivoCancelarConChequeRequest,
    PasivoCreate,
    PasivoPagoRequest,
    PasivoRead,
    PasivoUpdate,
)
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


@router.patch("/{pasivo_id}", response_model=PasivoRead)
def editar_pasivo(pasivo_id: UUID, payload: PasivoUpdate, db: DbSession) -> PasivoRead:
    return service.editar_pasivo(db, pasivo_id, payload)


@router.post("/{pasivo_id}/pagar", response_model=PasivoRead)
def pagar_pasivo(
    pasivo_id: UUID,
    payload: PasivoPagoRequest,
    db: DbSession,
) -> PasivoRead:
    return service.pagar_pasivo(db, pasivo_id, payload)


@router.post("/{pasivo_id}/cancelar-con-cheque", response_model=PasivoRead)
def cancelar_pasivo_con_cheque(
    pasivo_id: UUID,
    payload: PasivoCancelarConChequeRequest,
    db: DbSession,
) -> PasivoRead:
    return service.cancelar_con_cheque(db, pasivo_id, payload)
