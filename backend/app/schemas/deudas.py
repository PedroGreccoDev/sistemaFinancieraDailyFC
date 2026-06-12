from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DeudaEstado, DeudaTipo, Moneda


class DeudaCreate(BaseModel):
    cliente_id: UUID | None = None
    concepto: str = Field(min_length=1, max_length=500)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    tipo: DeudaTipo
    fecha_vencimiento: date | None = None
    observaciones: str | None = None


class DeudaCancelarRequest(BaseModel):
    fecha_cancelacion: date | None = None


class DeudaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID | None
    concepto: str
    monto: Decimal
    moneda: Moneda
    tipo: DeudaTipo
    estado: DeudaEstado
    fecha_vencimiento: date | None
    fecha_cancelacion: date | None
    observaciones: str | None
    created_at: datetime
    updated_at: datetime
