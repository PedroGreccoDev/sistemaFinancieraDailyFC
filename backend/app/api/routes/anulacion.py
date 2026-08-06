"""Rutas de anulación — el "Eliminar" del panel, para toda entidad de negocio.

Un router único porque el motor es genérico: el tipo de entidad viaja en la URL
(`/anulaciones/cheque/{id}`) en vez de haber un DELETE por módulo. Así hay un solo
lugar donde vive la semántica de "deshacer", que es justamente lo que evita que
cada sección invente su propia forma de borrar.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.anulacion import AnularRequest, ImpactoRead
from app.services import anulacion as service

router = APIRouter(prefix="/anulaciones", tags=["anulaciones"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/{entidad}/{entidad_id}", response_model=ImpactoRead)
def previsualizar(entidad: str, entidad_id: UUID, db: DbSession) -> ImpactoRead:
    """Devuelve el impacto de anular, sin tocar nada."""
    impacto = service.previsualizar(db, entidad, entidad_id)
    return ImpactoRead(
        entidad=impacto.entidad,
        entidad_id=impacto.entidad_id,
        descripcion=impacto.descripcion,
        puede_anular=impacto.puede_anular,
        bloqueo=impacto.bloqueo,
        lineas=impacto.lineas,
        arrastra=impacto.arrastra,
    )


@router.post("/{entidad}/{entidad_id}", response_model=ImpactoRead)
def anular(
    entidad: str,
    entidad_id: UUID,
    payload: AnularRequest,
    db: DbSession,
) -> ImpactoRead:
    """Anula la operación y revierte su rastro en el libro de caja."""
    impacto = service.anular(
        db,
        entidad,
        entidad_id,
        operador_id=payload.operador_id,
        motivo=payload.motivo,
    )
    return ImpactoRead(
        entidad=impacto.entidad,
        entidad_id=impacto.entidad_id,
        descripcion=impacto.descripcion,
        puede_anular=True,
        bloqueo=None,
        lineas=impacto.lineas,
        arrastra=impacto.arrastra,
    )
