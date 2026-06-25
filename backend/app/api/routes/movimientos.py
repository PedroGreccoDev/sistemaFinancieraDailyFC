from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.movimientos import (
    MovimientoEfectivoCreate,
    MovimientoEfectivoRead,
    MovimientoEfectivoUpdate,
)
from app.services import movimientos as service


router = APIRouter(prefix="/movimientos-efectivo", tags=["movimientos-efectivo"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=MovimientoEfectivoRead, status_code=201)
def create_movimiento(
    payload: MovimientoEfectivoCreate,
    db: DbSession,
) -> MovimientoEfectivoRead:
    return service.create_movimiento(db, payload)


@router.get("", response_model=list[MovimientoEfectivoRead])
def list_movimientos(db: DbSession) -> list[MovimientoEfectivoRead]:
    return service.list_movimientos(db)


@router.patch("/{movimiento_id}", response_model=MovimientoEfectivoRead)
def editar_movimiento(
    movimiento_id: UUID,
    payload: MovimientoEfectivoUpdate,
    db: DbSession,
) -> MovimientoEfectivoRead:
    return service.editar_movimiento(db, movimiento_id, payload)

