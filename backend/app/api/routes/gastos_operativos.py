from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.gastos_operativos import GastoOperativoCreate, GastoOperativoRead
from app.services import gastos_operativos as service

router = APIRouter(prefix="/gastos-operativos", tags=["gastos-operativos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=GastoOperativoRead, status_code=201)
def create_gasto(payload: GastoOperativoCreate, db: DbSession) -> GastoOperativoRead:
    return service.create_gasto(db, payload)


@router.get("", response_model=list[GastoOperativoRead])
def list_gastos(db: DbSession) -> list[GastoOperativoRead]:
    return service.list_gastos(db)
