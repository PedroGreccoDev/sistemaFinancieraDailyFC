from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.db.models import ChequeEstado
from app.db.session import get_db
from app.schemas.cheques import (
    ChequeCreate,
    ChequeFiarRequest,
    ChequeFiarResponse,
    ChequeManualTransition,
    ChequeRead,
    ChequeUpdate,
)
from app.services import cheques as service


router = APIRouter(prefix="/cheques", tags=["cheques"])

# Router público (montado SIN get_current_user en main.py): la foto se sirve por
# UUID no-adivinable para poder usarse en <img src> directos del panel, que no
# pueden enviar el header Authorization. La protección efectiva es la entropía
# del UUID, no la sesión.
public_router = APIRouter(prefix="/cheques", tags=["cheques"])

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


@router.get("/{cheque_id}", response_model=ChequeRead)
def get_cheque(cheque_id: UUID, db: DbSession) -> ChequeRead:
    return service.get_cheque(db, cheque_id)


@router.patch("/{cheque_id}", response_model=ChequeRead)
def editar_cheque(cheque_id: UUID, payload: ChequeUpdate, db: DbSession) -> ChequeRead:
    return service.editar_cheque(db, cheque_id, payload)


@public_router.get("/{cheque_id}/foto")
def get_cheque_foto(cheque_id: UUID, db: DbSession) -> Response:
    foto, mime = service.get_cheque_foto(db, cheque_id)
    return Response(
        content=foto,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.post("/{cheque_id}/transiciones", response_model=ChequeRead)
def transition_cheque(
    cheque_id: UUID,
    payload: ChequeManualTransition,
    db: DbSession,
) -> ChequeRead:
    return service.transition_cheque(db, cheque_id, payload)


@router.post("/{cheque_id}/fiar", response_model=ChequeFiarResponse)
def fiar_cheque(
    cheque_id: UUID,
    payload: ChequeFiarRequest,
    db: DbSession,
) -> ChequeFiarResponse:
    cheque, fiado = service.fiar_cheque(db, cheque_id, payload)
    return ChequeFiarResponse(cheque=cheque, fiado=fiado)

