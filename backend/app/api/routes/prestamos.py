from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import PrestamoEstado
from app.db.session import get_db
from app.schemas.prestamos import (
    CuotaCobroRequest,
    CuotaRead,
    PrestamoCreate,
    PrestamoRead,
)
from app.services import prestamos as service


router = APIRouter(prefix="/prestamos", tags=["prestamos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PrestamoRead, status_code=201)
def create_prestamo(payload: PrestamoCreate, db: DbSession) -> PrestamoRead:
    return service.create_prestamo(db, payload)


@router.get("", response_model=list[PrestamoRead])
def list_prestamos(
    db: DbSession,
    estado: PrestamoEstado | None = None,
) -> list[PrestamoRead]:
    return service.list_prestamos(db, estado)


@router.get("/{prestamo_id}", response_model=PrestamoRead)
def get_prestamo(prestamo_id: UUID, db: DbSession) -> PrestamoRead:
    return service.get_prestamo(db, prestamo_id)


@router.post("/{prestamo_id}/cuotas/{cuota_id}/cobros", response_model=CuotaRead)
def cobrar_cuota(
    prestamo_id: UUID,
    cuota_id: UUID,
    payload: CuotaCobroRequest,
    db: DbSession,
) -> CuotaRead:
    return service.cobrar_cuota(db, prestamo_id, cuota_id, payload.fecha_cobro)

