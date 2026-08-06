from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DeudaSimpleEstado, Moneda
from app.schemas.cheques import ChequeRead


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


class DeudaSimpleCobrarConChequeRequest(BaseModel):
    """Cobro de una deuda libre entregando un cheque en vez de efectivo.

    El cheque entra a cartera a nombre del cliente de la deuda y vale su
    `valor_neto = monto_cheque × (1 − porcentaje_compra_cheque / 100)`.

    Los cheques son SIEMPRE en pesos, así que cobrar con cheque una deuda en USD
    cruza monedas y exige `cotizacion` ($/USD) — igual que el cobro en efectivo.
    """

    nro_cheque_pago: str = Field(min_length=1, max_length=64)
    banco_pago: str | None = Field(default=None, max_length=120)
    monto_cheque: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra_cheque: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    # Obligatoria solo si la deuda es en USD (el cheque siempre entra en ARS).
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha_cobro: date | None = None


class DeudaSimpleCobrarConChequeResponse(BaseModel):
    """Resultado del cobro con cheque.

    `diferencia` en la moneda de la deuda: > 0 el cheque valía más que el saldo y
    el negocio le queda debiendo esa diferencia al cliente; < 0 el cliente todavía
    debe el resto; 0 justo.
    """

    deuda: DeudaSimpleRead
    cheque_ingresado: ChequeRead
    diferencia: Decimal
