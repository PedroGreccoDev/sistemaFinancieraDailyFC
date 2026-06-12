from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import Moneda, PasivoEstado


class PasivoCreate(BaseModel):
    acreedor: str = Field(min_length=1, max_length=200)
    concepto: str = Field(min_length=1)
    monto: Decimal = Field(gt=0)
    moneda: Moneda
    fecha_vencimiento: date | None = None
    observaciones: str | None = None


class PasivoCancelarRequest(BaseModel):
    fecha_cancelacion: date | None = None


class PasivoCancelarEfectivoRequest(BaseModel):
    fecha_cancelacion: date | None = None


class PasivoCancelarConChequeRequest(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    porcentaje_venta: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    fecha_cancelacion: date | None = None


class PasivoRead(BaseModel):
    id: UUID
    acreedor: str
    concepto: str
    monto: Decimal
    moneda: Moneda
    estado: PasivoEstado
    fecha_vencimiento: date | None
    fecha_cancelacion: date | None
    observaciones: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
