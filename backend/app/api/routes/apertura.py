"""Rutas de apertura del sistema — los saldos con los que arrancó el negocio.

Dos operaciones de puesta en marcha: fijar hasta cuándo los cheques que se cargan
son cartera preexistente, y cargar el efectivo que había en el cajón.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.apertura import (
    ConfiguracionAperturaRead,
    FechaCorteRequest,
    FechaCorteResponse,
    SaldoInicialRequest,
)
from app.services import apertura as service

router = APIRouter(prefix="/apertura", tags=["apertura"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("", response_model=ConfiguracionAperturaRead)
def get_apertura(db: DbSession) -> ConfiguracionAperturaRead:
    """Estado actual: qué falta definir y qué ya quedó fijado."""
    return service.get_configuracion(db)


@router.post("/fecha-corte", response_model=FechaCorteResponse)
def definir_fecha_corte(payload: FechaCorteRequest, db: DbSession) -> FechaCorteResponse:
    """Fija hasta qué día los cheques cargados son cartera preexistente.

    Corrige además hacia atrás: a los cheques ya cargados dentro del período les
    quita el egreso de compra que no correspondía."""
    resultado = service.definir_fecha_corte(
        db, payload.fecha_corte, operador_id=payload.operador_id
    )
    return FechaCorteResponse(fecha_corte=payload.fecha_corte, **resultado)


@router.post("/saldo-inicial", response_model=ConfiguracionAperturaRead)
def definir_saldo_inicial(
    payload: SaldoInicialRequest, db: DbSession
) -> ConfiguracionAperturaRead:
    """Carga el efectivo de arranque, por moneda. Por única vez."""
    return service.definir_saldo_inicial(
        db,
        saldo_ars=payload.saldo_ars,
        saldo_usd=payload.saldo_usd,
        cotizacion_usd=payload.cotizacion_usd,
        fecha=payload.fecha,
        operador_id=payload.operador_id,
        forzar=payload.forzar,
    )
