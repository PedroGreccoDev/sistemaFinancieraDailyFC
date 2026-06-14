from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import Moneda


class GastoOperativoCreate(BaseModel):
    concepto: str = Field(min_length=1, max_length=300)
    monto: Decimal = Field(gt=0)
    moneda: Moneda = Moneda.ARS
    fecha_operacion: date | None = None
    hora_operacion: time | None = None
    observaciones: str | None = None


class GastoOperativoRead(BaseModel):
    id: UUID
    concepto: str
    monto: Decimal
    moneda: Moneda
    fecha_operacion: date
    hora_operacion: time | None
    observaciones: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
