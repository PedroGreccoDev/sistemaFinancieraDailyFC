from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import ChequeEstado
from app.db.session import get_db
from app.schemas.cheques import (
    ChequeCreate,
    ChequeFiarRequest,
    ChequeFiarResponse,
    ChequeManualTransition,
    ChequeRead,
)
from app.services import cheques as service


router = APIRouter(prefix="/cheques", tags=["cheques"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ChequeRead, status_code=201)
def create_cheque(payload: ChequeCreate, db: DbSession) -> ChequeRead:
    return service.create_cheque(db, payload)


@router.get("", response_model=list[ChequeRead])
def list_cheques(db: DbSession, estado: ChequeEstado | None = None) -> list[ChequeRead]:
    return service.list_cheques(db, estado)


@router.get("/cartera", response_model=list[ChequeRead])
def list_cartera(db: DbSession) -> list[ChequeRead]:
    return service.list_cheques(db, ChequeEstado.EN_CARTERA)


@router.get("/{nro_cheque}", response_model=ChequeRead)
def get_cheque(nro_cheque: str, db: DbSession) -> ChequeRead:
    return service.get_cheque(db, nro_cheque)


@router.post("/{nro_cheque}/transiciones", response_model=ChequeRead)
def transition_cheque(
    nro_cheque: str,
    payload: ChequeManualTransition,
    db: DbSession,
) -> ChequeRead:
    return service.transition_cheque(db, nro_cheque, payload)


@router.post("/{nro_cheque}/fiar", response_model=ChequeFiarResponse)
def fiar_cheque(
    nro_cheque: str,
    payload: ChequeFiarRequest,
    db: DbSession,
) -> ChequeFiarResponse:
    cheque, fiado = service.fiar_cheque(db, nro_cheque, payload)
    return ChequeFiarResponse(cheque=cheque, fiado=fiado)

