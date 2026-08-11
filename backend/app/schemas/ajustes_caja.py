from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import AjusteCajaMotivo, CajaTipo, Moneda


class AjusteCajaCreate(BaseModel):
    """Alta de un ajuste manual de caja.

    `monto` es siempre positivo: el sentido lo da `tipo` (INGRESO suma efectivo a
    la caja, EGRESO lo resta). `cotizacion_usd` es obligatoria cuando el ajuste
    **suma USD**: sin ella el lote no se puede armar y esos dólares quedarían en la
    caja sin poder venderse.
    """

    fecha: date
    moneda: Moneda = Moneda.ARS
    tipo: CajaTipo
    motivo: AjusteCajaMotivo
    monto: Decimal = Field(gt=0)
    cotizacion_usd: Decimal | None = Field(default=None, gt=0)
    descripcion: str | None = None
    operador_id: str = Field(min_length=1, max_length=80)


class AjusteCajaRead(BaseModel):
    id: UUID
    fecha: date
    moneda: Moneda
    tipo: CajaTipo
    motivo: AjusteCajaMotivo
    monto: Decimal
    cotizacion_usd: Decimal | None
    lote_id: UUID | None
    descripcion: str | None
    operador_id: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
