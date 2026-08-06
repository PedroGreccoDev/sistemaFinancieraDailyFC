from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import DeudaSimpleEstado
from app.db.session import get_db
from app.schemas.deudas_simples import (
    DeudaSimpleCobrarConChequeRequest,
    DeudaSimpleCobrarConChequeResponse,
    DeudaSimpleCreate,
    DeudaSimplePagoRequest,
    DeudaSimpleRead,
    DeudaSimpleUpdate,
)
from app.services import deudas_simples as service


router = APIRouter(prefix="/deudas-simples", tags=["deudas-simples"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=list[DeudaSimpleRead])
def list_deudas(
    db: DbSession, estado: DeudaSimpleEstado | None = None
) -> list[DeudaSimpleRead]:
    return service.list_deudas_simples(db, estado)


@router.post("", response_model=DeudaSimpleRead, status_code=201)
def crear_deuda(payload: DeudaSimpleCreate, db: DbSession) -> DeudaSimpleRead:
    return service.create_deuda_simple(db, payload)


@router.get("/{deuda_id}", response_model=DeudaSimpleRead)
def get_deuda(deuda_id: UUID, db: DbSession) -> DeudaSimpleRead:
    return service.get_deuda_simple(db, deuda_id)


@router.patch("/{deuda_id}", response_model=DeudaSimpleRead)
def editar_deuda(
    deuda_id: UUID, payload: DeudaSimpleUpdate, db: DbSession
) -> DeudaSimpleRead:
    return service.editar_deuda_simple(db, deuda_id, payload)


@router.post("/{deuda_id}/cobrar", response_model=DeudaSimpleRead)
def cobrar_deuda(
    deuda_id: UUID, payload: DeudaSimplePagoRequest, db: DbSession
) -> DeudaSimpleRead:
    return service.cobrar_deuda_simple(db, deuda_id, payload)


@router.post("/{deuda_id}/cobrar-con-cheque", response_model=DeudaSimpleCobrarConChequeResponse)
def cobrar_deuda_con_cheque(
    deuda_id: UUID, payload: DeudaSimpleCobrarConChequeRequest, db: DbSession
) -> DeudaSimpleCobrarConChequeResponse:
    """El cliente paga la deuda con un cheque en vez de efectivo.

    El cheque entra a cartera a su nombre y salda por su valor neto. No asienta
    caja: la plata se reconoce recién cuando ese cheque se venda o se cobre."""
    return service.cobrar_con_cheque(db, deuda_id, payload)
