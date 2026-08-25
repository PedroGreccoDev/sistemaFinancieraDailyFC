"""Schemas del traspaso entre cajas (§Caja paralela)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import MedioPago, Moneda


class TraspasoCreate(BaseModel):
    """Plata que pasa de una caja a la otra: un depósito o una extracción.

    `origen` y `destino` tienen que ser distintos — mover plata dentro de la misma
    caja no es nada—. No hay `tipo`: depositar es EFECTIVO → TRANSFERENCIA y
    extraer es al revés, así que el sentido ya lo dicen los dos campos.
    """

    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda = Moneda.ARS
    origen: MedioPago
    destino: MedioPago
    fecha: date | None = None
    detalle: str | None = Field(default=None, max_length=300)


class TraspasoRead(BaseModel):
    id: UUID
    fecha: date
    moneda: Moneda
    monto: Decimal
    origen: MedioPago
    destino: MedioPago
    detalle: str | None
