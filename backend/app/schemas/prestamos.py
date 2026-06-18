from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import CuotaEstado, FrecuenciaCuotas, Moneda, PrestamoEstado
from app.schemas.cheques import ChequeRead


class PrestamoBase(BaseModel):
    credito: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    cuotas: int = Field(gt=0)
    frecuencia: FrecuenciaCuotas
    total_a_cobrar: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_inicio: date | None = None

    @model_validator(mode="after")
    def validate_total(self) -> PrestamoBase:
        if self.total_a_cobrar < self.credito:
            raise ValueError("total_a_cobrar debe ser mayor o igual al credito")
        return self


class PrestamoCreate(PrestamoBase):
    cliente_id: UUID


class PrestamoCreateFromCheque(PrestamoBase):
    pass


class CuotaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prestamo_id: UUID
    numero_cuota: int
    fecha_vencimiento: date
    monto: Decimal
    estado: CuotaEstado
    fecha_cobro: date | None
    created_at: datetime
    updated_at: datetime


class PrestamoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID
    credito: Decimal
    moneda: Moneda
    cuotas: int
    frecuencia: FrecuenciaCuotas
    total_a_cobrar: Decimal
    ganancia: Decimal
    estado: PrestamoEstado
    fecha_inicio: date
    cuotas_detalle: list[CuotaRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class CuotaCobroRequest(BaseModel):
    fecha_cobro: date | None = None


class CuotaCobrarConChequeRequest(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    cliente_origen_id: UUID | None = None
    fecha_cobro: date | None = None


class CuotaCobrarConChequeResponse(BaseModel):
    cuota: CuotaRead
    cheque: ChequeRead
