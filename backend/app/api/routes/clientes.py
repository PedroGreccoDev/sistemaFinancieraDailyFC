from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.clientes import ClienteCreate, ClienteRead
from app.services import clientes as service


router = APIRouter(prefix="/clientes", tags=["clientes"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=ClienteRead, status_code=201)
def create_cliente(payload: ClienteCreate, db: DbSession) -> ClienteRead:
    return service.create_cliente(db, payload)


@router.get("", response_model=list[ClienteRead])
def list_clientes(db: DbSession) -> list[ClienteRead]:
    return service.list_clientes(db)


@router.get("/{cliente_id}", response_model=ClienteRead)
def get_cliente(cliente_id: UUID, db: DbSession) -> ClienteRead:
    return service.get_cliente(db, cliente_id)

