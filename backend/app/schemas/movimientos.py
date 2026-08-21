from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

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
    # Pesos efectivamente abonados en una COMPRA. None = se pagó todo, que es la
    # operación normal y el comportamiento de siempre. Si es menor a
    # `monto × cotizacion`, la diferencia queda a deber: no sale de la caja y
    # genera el pasivo con el vendedor (§Comprar sin abonar).
    monto_abonado: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )

    @model_validator(mode="after")
    def validate_monto_abonado(self) -> "MovimientoEfectivoCreate":
        if self.monto_abonado is None:
            return self
        # Vender a crédito no es esto: acá el que queda debiendo sería el cliente,
        # y esa es una deuda de cliente (§2.b), no un pasivo del negocio.
        if self.tipo is not MovimientoEfectivoTipo.COMPRA:
            raise ValueError(
                "Solo una COMPRA puede quedar a deber. Si vendiste y te quedaron "
                "debiendo, cargalo como deuda del cliente."
            )
        pesos = (self.monto * self.cotizacion_aplicada).quantize(Decimal("0.01"))
        if self.monto_abonado > pesos:
            raise ValueError(
                f"Abonaste ${self.monto_abonado} y la compra es de ${pesos}: "
                "el monto abonado no puede superar el total."
            )
        # A deber hay que saber a quién: sin vendedor no se puede armar el pasivo.
        if self.monto_abonado < pesos and self.cliente_id is None:
            raise ValueError(
                "Una compra a deber necesita el vendedor: indicá a quién le "
                "quedás debiendo."
            )
        return self


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
    # Pesos abonados. None = se pagó todo; menos que `monto × cotizacion` significa
    # que hay un pasivo abierto con el vendedor (§Comprar sin abonar).
    monto_abonado: Decimal | None
    ganancia: Decimal
    usd_restante: Decimal
    fecha_operacion: datetime
    observaciones: str | None
    created_at: datetime
    updated_at: datetime

