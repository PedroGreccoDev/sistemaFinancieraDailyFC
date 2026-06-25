from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Moneda, MovimientoEfectivoTipo


class MovimientoEfectivoCreate(BaseModel):
    cliente_id: UUID | None = None
    tipo: MovimientoEfectivoTipo
    moneda: Moneda
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    cotizacion_aplicada: Decimal = Field(gt=0, max_digits=18, decimal_places=6)
    # La ganancia se calcula server-side por lotes FIFO en la venta; este campo de
    # entrada se acepta por compatibilidad pero se ignora.
    ganancia: Decimal = Field(default=Decimal("0.00"), max_digits=18, decimal_places=2)
    fecha_operacion: datetime | None = None
    observaciones: str | None = None


class MovimientoEfectivoUpdate(BaseModel):
    """Corrección de una operación de divisas desde el panel.

    Solo campos opcionales (`exclude_unset`). El servicio aplica las reglas FIFO:
    una COMPRA solo se edita si su lote está intacto (`usd_restante == monto`); una
    VENTA solo si es la última (no hay ventas posteriores que dependan de su
    imputación). `cliente_id`/`observaciones` se pueden editar siempre. No se permite
    cambiar `tipo` ni `moneda` (rehacen la operación entera)."""

    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    cotizacion_aplicada: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )
    cliente_id: UUID | None = None
    observaciones: str | None = None


class MovimientoEfectivoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID | None
    tipo: MovimientoEfectivoTipo
    moneda: Moneda
    monto: Decimal
    cotizacion_aplicada: Decimal
    ganancia: Decimal
    usd_restante: Decimal
    fecha_operacion: datetime
    observaciones: str | None
    created_at: datetime
    updated_at: datetime

