from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import MedioPago, Moneda, PasivoEstado

# Qué hacer con el vuelto cuando un cheque cubre de más un pasivo.
VueltoModo = Literal["SALDAR_EFECTIVO", "QUEDA_DEBIENDO"]


class PasivoCreate(BaseModel):
    acreedor: str = Field(min_length=1, max_length=200)
    concepto: str = Field(min_length=1)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    fecha_vencimiento: date | None = None
    observaciones: str | None = None


class PasivoUpdate(BaseModel):
    """Corrección de la carga de una deuda desde el panel.

    Campos opcionales (`exclude_unset`). `acreedor`, `concepto`, `fecha_vencimiento`
    y `observaciones` se editan siempre. `monto`/`moneda` solo si la deuda está
    PENDIENTE y sin pagos parciales (saldo == monto); el servicio recalcula el saldo."""

    acreedor: str | None = Field(default=None, min_length=1, max_length=200)
    concepto: str | None = Field(default=None, min_length=1)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda | None = None
    fecha_vencimiento: date | None = None
    observaciones: str | None = None


class PasivoPagoRequest(BaseModel):
    """Pago de una deuda (total o parcial) en efectivo o transferencia.

    `monto_pagado` es el dinero que sale de caja, en `moneda_pago` (la moneda con
    la que se paga, que puede diferir de la moneda de la deuda). `cotizacion`
    ($/USD) es obligatoria solo cuando `moneda_pago` ≠ moneda de la deuda; se usa
    para imputar cuánto de la deuda quedó saldado."""

    monto_pagado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    medio_pago: MedioPago
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha_cancelacion: date | None = None


class PasivoCancelarConChequeRequest(BaseModel):
    cheque_id: UUID
    porcentaje_venta: Decimal = Field(ge=Decimal("0"), le=Decimal("100"))
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    fecha_cancelacion: date | None = None
    # Solo se usa si el cheque cubre de más (diferencia > 0): el operador elige si
    # paga el vuelto en efectivo/transferencia (SALDAR_EFECTIVO) o queda debiendo
    # al cliente y se crea un pasivo a su favor (QUEDA_DEBIENDO).
    vuelto_modo: VueltoModo | None = None


class PasivoRead(BaseModel):
    id: UUID
    acreedor: str
    concepto: str
    monto: Decimal
    saldo_pendiente: Decimal
    moneda: Moneda
    estado: PasivoEstado
    fecha_vencimiento: date | None
    fecha_cancelacion: date | None
    observaciones: str | None
    # Cotización de la primera cancelación cross-moneda; default para los pagos siguientes.
    cotizacion_pago: Decimal | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
