from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import FiadoEstado, Moneda


class FiadoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cheque_nro: str
    cliente_id: UUID
    monto_original: Decimal
    porcentaje_venta: Decimal
    saldo_pendiente: Decimal
    estado: FiadoEstado
    fecha_fiado: date
    created_at: datetime
    updated_at: datetime


class FiadoCobrarEfectivoRequest(BaseModel):
    """Cobro de un fiado (total o parcial) en efectivo.

    La deuda del fiado está siempre en ARS (los cheques son en pesos). `monto_cobrado`
    es lo que entra a caja, en `moneda_pago` (que puede diferir de la deuda). `cotizacion`
    ($/USD) es obligatoria solo cuando `moneda_pago` ≠ ARS; imputa cuánto baja el saldo.
    """

    monto_cobrado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    operador_id: str = Field(min_length=1, max_length=80)
    moneda_pago: Moneda = Moneda.ARS
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)


class FiadoCobrarConChequeRequest(BaseModel):
    nro_cheque_pago: str = Field(min_length=1, max_length=64)
    banco_pago: str | None = Field(default=None, max_length=120)
    monto_cheque: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra_cheque: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    operador_id: str = Field(min_length=1, max_length=80)
