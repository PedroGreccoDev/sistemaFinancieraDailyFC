from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ConfiguracionAperturaRead(BaseModel):
    """Estado de la apertura del sistema (qué falta definir y qué ya se definió)."""

    model_config = ConfigDict(from_attributes=True)

    fecha_corte_carga_inicial: date | None = None
    saldo_inicial_ars: Decimal | None = None
    saldo_inicial_usd: Decimal | None = None
    cotizacion_usd_inicial: Decimal | None = None
    fecha_saldo_inicial: date | None = None
    definido_por: str | None = None
    definido_at: datetime | None = None
    saldo_definido: bool = False


class FechaCorteRequest(BaseModel):
    """Hasta qué día los cheques que se cargan son cartera preexistente."""

    fecha_corte: date
    operador_id: str = Field(min_length=1, max_length=80)


class FechaCorteResponse(BaseModel):
    """Qué se corrigió hacia atrás al fijar el corte."""

    fecha_corte: date
    cheques_marcados: int
    lineas_revertidas: int


class SaldoInicialRequest(BaseModel):
    """Efectivo en mano al arrancar, con el día al que corresponde.

    `fecha` es el día del efectivo, NO el día en que se carga: se puede tipear
    una semana después y el reporte igual cierra bien para atrás.
    """

    saldo_ars: Decimal = Field(ge=0)
    saldo_usd: Decimal = Field(ge=0)
    # $/USD promedio al que se consiguieron esos dólares. Obligatoria si
    # `saldo_usd > 0`: sin ella no se puede armar el lote, y sin lote los dólares
    # quedan en la caja pero no se pueden vender.
    cotizacion_usd: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha: date
    operador_id: str = Field(min_length=1, max_length=80)
    # El saldo de apertura es por única vez; rehacerlo requiere pedirlo explícito.
    forzar: bool = False
