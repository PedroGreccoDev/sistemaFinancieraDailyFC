from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import ChequeEstado
from app.schemas.prestamos import PrestamoCreateFromCheque, PrestamoRead


class ChequeCreate(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None


class ChequeManualTransition(BaseModel):
    target_state: ChequeEstado
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    porcentaje_venta: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_destino_id: UUID | None = None


class ChequeFiarRequest(BaseModel):
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    cliente_destino_id: UUID
    prestamo: PrestamoCreateFromCheque


class ChequeRead(BaseModel):
    class Config:
        from_attributes = True

    nro_cheque: str
    monto: Decimal
    fecha_emision: date | None
    fecha_pago: date | None
    porcentaje_compra: Decimal
    porcentaje_venta: Decimal | None
    ganancia: Decimal
    estado: ChequeEstado
    ultimo_evento_manual_at: datetime | None
    ultimo_operador_id: str | None
    ultimo_motivo_manual: str | None
    cliente_origen_id: UUID | None
    cliente_destino_id: UUID | None
    created_at: datetime
    updated_at: datetime


class ChequeFiarResponse(BaseModel):
    cheque: ChequeRead
    prestamo: PrestamoRead

