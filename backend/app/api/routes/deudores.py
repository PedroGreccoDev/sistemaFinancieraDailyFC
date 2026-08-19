from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Moneda
from app.db.session import get_db
from app.schemas.deudores import (
    CobroClienteChequeCreate,
    CobroClienteChequeResponse,
    CobroClienteCreate,
    CobroClienteResponse,
    DeudaClienteResumen,
)
from app.services import deudores as service


router = APIRouter(prefix="/deudores", tags=["deudores"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/clientes/{cliente_id}", response_model=DeudaClienteResumen)
def resumen_cliente(
    cliente_id: UUID, db: DbSession, moneda: Moneda = Moneda.ARS
) -> DeudaClienteResumen:
    """Cuánto debe un cliente en una moneda, sumando sus tres fuentes de deuda.

    Los cheques fiados son siempre en pesos; en USD solo entran deudas libres y
    préstamos en dólares."""
    return service.resumen_cliente(db, cliente_id, moneda)


@router.post("/cobrar-cliente", response_model=CobroClienteResponse)
def cobrar_cliente(
    payload: CobroClienteCreate, db: DbSession
) -> CobroClienteResponse:
    """Cobra un importe libre contra toda la deuda del cliente, en efectivo.

    Se imputa de la operación más vieja a la más nueva cruzando fiados, deudas
    libres y préstamos; cada operación alcanzada asienta su propia línea de
    caja."""
    return service.cobrar_cliente(db, payload)


@router.post("/cobrar-cliente-con-cheque", response_model=CobroClienteChequeResponse)
def cobrar_cliente_con_cheque(
    payload: CobroClienteChequeCreate, db: DbSession
) -> CobroClienteChequeResponse:
    """Cobra toda la deuda del cliente con un solo cheque.

    Salda por el valor neto del cheque, de la operación más vieja a la más
    nueva, y no mueve caja: el cheque entra a cartera. Si cubre todo y sobra,
    `vuelto_modo` decide qué se hace con la diferencia."""
    return service.cobrar_cliente_con_cheque(db, payload)
