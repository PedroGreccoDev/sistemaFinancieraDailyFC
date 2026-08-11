"""Rutas de ajustes de caja — agregar o restar efectivo a mano.

Solo alta y listado: **no hay edición**. Un ajuste en dólares mueve la cadena FIFO,
y editarlo obligaría a reescribir imputaciones ya hechas. Corregir uno mal cargado
se hace anulándolo (`POST /anulaciones/ajuste_caja/{id}`) y cargándolo de nuevo,
que además deja el rastro de qué se corrigió y por qué.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.ajustes_caja import AjusteCajaCreate, AjusteCajaRead
from app.services import ajustes_caja as service

router = APIRouter(prefix="/ajustes-caja", tags=["ajustes-caja"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=AjusteCajaRead, status_code=201)
def crear_ajuste(payload: AjusteCajaCreate, db: DbSession) -> AjusteCajaRead:
    """Registra el ajuste y asienta su línea en el libro de caja."""
    return service.crear_ajuste(
        db,
        fecha=payload.fecha,
        moneda=payload.moneda,
        tipo=payload.tipo,
        motivo=payload.motivo,
        monto=payload.monto,
        cotizacion_usd=payload.cotizacion_usd,
        descripcion=payload.descripcion,
        operador_id=payload.operador_id,
    )


@router.get("", response_model=list[AjusteCajaRead])
def list_ajustes(
    db: DbSession,
    desde: Annotated[date | None, Query()] = None,
    hasta: Annotated[date | None, Query()] = None,
) -> list[AjusteCajaRead]:
    return service.list_ajustes(db, desde, hasta)
