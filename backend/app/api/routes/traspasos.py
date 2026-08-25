"""Rutas del traspaso entre cajas — depositar y extraer.

Solo alta, listado y anulación: **no hay edición**. Un traspaso son dos líneas de
caja enlazadas y nada más; corregir uno mal cargado es borrarlo y volver a
cargarlo, que además no deja media operación viva si algo sale mal.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.traspasos import TraspasoCreate, TraspasoRead
from app.services import traspasos as service

router = APIRouter(prefix="/traspasos", tags=["traspasos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=TraspasoRead, status_code=201)
def crear_traspaso(payload: TraspasoCreate, db: DbSession) -> TraspasoRead:
    """Pasa plata de una caja a la otra. No cambia el total del negocio."""
    t = service.registrar(
        db,
        monto=payload.monto,
        moneda=payload.moneda,
        origen=payload.origen,
        destino=payload.destino,
        fecha=payload.fecha,
        detalle=payload.detalle,
    )
    return TraspasoRead(**t.__dict__)


@router.get("", response_model=list[TraspasoRead])
def listar_traspasos(
    db: DbSession,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> list[TraspasoRead]:
    return [TraspasoRead(**t.__dict__) for t in service.listar(db, desde, hasta)]


@router.delete("/{traspaso_id}", status_code=status.HTTP_204_NO_CONTENT, response_class=Response)
def anular_traspaso(traspaso_id: UUID, db: DbSession) -> Response:
    """Deshace el traspaso entero: las dos líneas o ninguna."""
    service.anular(db, traspaso_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
