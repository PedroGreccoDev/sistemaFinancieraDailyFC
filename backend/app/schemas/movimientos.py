from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Moneda, MovimientoEfectivoTipo


class MovimientoEfectivoCreate(BaseModel):
    cliente_id: UUID | None = None
    tipo: MovimientoEfectivoTipo
    moneda: Moneda
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    cotizacion_aplicada: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    ganancia: Decimal = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)
    fecha_operacion: datetime | None = None
    observaciones: str | None = None


class MovimientoEfectivoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID | None
    tipo: MovimientoEfectivoTipo
    moneda: Moneda
    monto: Decimal
    cotizacion_aplicada: Decimal
    ganancia: Decimal
    fecha_operacion: datetime
    observaciones: str | None
    created_at: datetime
    updated_at: datetime

