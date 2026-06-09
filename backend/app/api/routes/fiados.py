from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import FiadoEstado
from app.db.session import get_db
from app.schemas.cheques import FiadoCobrarConChequeResponse
from app.schemas.fiados import (
    FiadoCobrarConChequeRequest,
    FiadoCobrarEfectivoRequest,
    FiadoRead,
)
from app.services import fiados as service


router = APIRouter(prefix="/fiados", tags=["fiados"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[FiadoRead])
def list_fiados(db: DbSession, estado: FiadoEstado | None = None) -> list[FiadoRead]:
    return service.list_fiados(db, estado)


@router.get("/{fiado_id}", response_model=FiadoRead)
def get_fiado(fiado_id: UUID, db: DbSession) -> FiadoRead:
    return service.get_fiado(db, fiado_id)


@router.post("/{fiado_id}/cobrar-efectivo", response_model=FiadoRead)
def cobrar_efectivo(
    fiado_id: UUID,
    payload: FiadoCobrarEfectivoRequest,
    db: DbSession,
) -> FiadoRead:
    return service.cobrar_con_efectivo(db, fiado_id, payload)


@router.post("/{fiado_id}/cobrar-con-cheque", response_model=FiadoCobrarConChequeResponse)
def cobrar_con_cheque(
    fiado_id: UUID,
    payload: FiadoCobrarConChequeRequest,
    db: DbSession,
) -> FiadoCobrarConChequeResponse:
    return service.cobrar_con_cheque(db, fiado_id, payload)
