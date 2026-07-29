from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DeudaSimpleEstado, Moneda


class DeudaSimpleCreate(BaseModel):
    """Alta de una deuda libre de un cliente (sin cuotas ni cheque).

    Registrarla saca la plata de la caja (EGRESO en `moneda`, con fecha `fecha`).
    """

    cliente_id: UUID
    concepto: str = Field(min_length=1)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    fecha: date | None = None
    observaciones: str | None = None


class DeudaSimpleUpdate(BaseModel):
    """Corrección de la carga de una deuda libre desde el panel.

    Campos opcionales (`exclude_unset`). `concepto`, `fecha` y `observaciones` se
    editan siempre. `monto`/`moneda` solo si está ABIERTA y sin cobros parciales
    (saldo == monto); el servicio recalcula el saldo y resincroniza el egreso."""

    concepto: str | None = Field(default=None, min_length=1)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda | None = None
    fecha: date | None = None
    observaciones: str | None = None


class DeudaSimplePagoRequest(BaseModel):
    """Cobro de una deuda libre (total o parcial), en efectivo.

    `monto_cobrado` es lo que entra a caja, en `moneda_pago` (que puede diferir de
    la moneda de la deuda). `cotizacion` ($/USD) es obligatoria solo cuando
    `moneda_pago` ≠ moneda de la deuda; imputa cuánto del saldo queda saldado."""

    monto_cobrado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha_cobro: date | None = None


class DeudaSimpleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID
    concepto: str
    monto: Decimal
    saldo_pendiente: Decimal
    moneda: Moneda
    estado: DeudaSimpleEstado
    fecha: date
    fecha_cancelacion: date | None
    observaciones: str | None
    cotizacion_pago: Decimal | None
    created_at: datetime
    updated_at: datetime
