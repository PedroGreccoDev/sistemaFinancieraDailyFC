from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import Cliente
from app.schemas.clientes import ClienteCreate
from app.services.exceptions import ConflictError, DatabaseWriteError, NotFoundError


def create_cliente(db: Session, payload: ClienteCreate) -> Cliente:
    cliente = Cliente(**payload.model_dump())
    try:
        db.add(cliente)
        db.commit()
        db.refresh(cliente)
        return cliente
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cliente con esos datos unicos.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el cliente.") from exc


def get_cliente(db: Session, cliente_id: uuid.UUID) -> Cliente:
    cliente = db.get(Cliente, cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")
    return cliente


def list_clientes(db: Session) -> list[Cliente]:
    return list(db.scalars(select(Cliente).order_by(Cliente.nombre.asc())))

