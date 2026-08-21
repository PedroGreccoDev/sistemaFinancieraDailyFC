from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.compensaciones import (
    CompensacionCreate,
    CompensacionRead,
    CompensacionResponse,
)
from app.services import compensaciones as service


router = APIRouter(prefix="/compensaciones", tags=["compensaciones"])

DbSession = Annotated[Session, Depends(get_db)]


class RevertirRequest(BaseModel):
    """Deshacer una compensación exige operador y motivo, como toda reversión."""

    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)


class RevertirResponse(BaseModel):
    """Qué se restituyó, para mostrárselo al operador."""

    id: UUID
    restituido: list[str]


@router.post("", response_model=CompensacionResponse, status_code=201)
def compensar(payload: CompensacionCreate, db: DbSession) -> CompensacionResponse:
    """El cliente le transfiere a un acreedor del negocio: bajan las dos deudas.

    No mueve la caja —esa plata nunca pasó por acá—. Del lado del cliente imputa
    de la deuda más vieja a la más nueva cruzando fiados, deudas libres y
    préstamos; del lado del acreedor, entre todas las deudas que el negocio le
    tiene, también de la más vieja a la más nueva. Si el cliente transfirió más
    de lo que debía, el excedente le queda a favor."""
    return service.compensar(db, payload)


@router.get("", response_model=list[CompensacionRead])
def list_compensaciones(
    db: DbSession,
    cliente_id: UUID | None = None,
    acreedor: str | None = None,
) -> list[CompensacionRead]:
    """Compensaciones registradas, filtrables por cliente o por acreedor."""
    return service.list_compensaciones(db, cliente_id=cliente_id, acreedor=acreedor)


@router.post("/{compensacion_id}/revertir", response_model=RevertirResponse)
def revertir(
    compensacion_id: UUID, payload: RevertirRequest, db: DbSession
) -> RevertirResponse:
    """Deshace la compensación: las dos deudas vuelven a como estaban.

    Al cliente se le devuelve exactamente lo que se le imputó a cada renglón (no
    un recálculo: entre medio pudo recibir otros cobros) y al acreedor lo que se
    le descontó. Si el excedente que le quedó a favor al cliente ya se usó, se
    bloquea."""
    restituido = service.revertir(
        db,
        compensacion_id,
        operador_id=payload.operador_id,
        motivo=payload.motivo,
    )
    return RevertirResponse(id=compensacion_id, restituido=restituido)
