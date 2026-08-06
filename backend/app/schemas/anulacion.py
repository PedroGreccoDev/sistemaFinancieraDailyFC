from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LineaImpactoRead(BaseModel):
    """Una línea del libro de caja que la anulación va a revertir."""

    model_config = ConfigDict(from_attributes=True)

    fecha: str
    moneda: str
    tipo: str
    categoria: str
    monto: Decimal
    detalle: str | None = None


class ImpactoRead(BaseModel):
    """Qué pasa (o pasaría) al anular una operación.

    El panel pide esto antes de mostrar el diálogo de confirmación: así el
    operador ve exactamente qué movimientos de caja se van a deshacer, en vez de
    apretar "Eliminar" a ciegas.
    """

    model_config = ConfigDict(from_attributes=True)

    entidad: str
    entidad_id: uuid.UUID
    descripcion: str
    puede_anular: bool
    bloqueo: str | None = None
    lineas: list[LineaImpactoRead] = Field(default_factory=list)
    arrastra: list[str] = Field(default_factory=list)


class AnularRequest(BaseModel):
    """Toda anulación queda firmada: quién y por qué."""

    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)


class RevertirRequest(AnularRequest):
    """Misma firma que anular: revertir también es una operación auditada."""
