from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ChequeEstado
from app.schemas.fiados import FiadoRead


class ChequeCreate(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None

    @model_validator(mode="after")
    def validate_fechas(self) -> "ChequeCreate":
        if (
            self.fecha_emision is not None
            and self.fecha_pago is not None
            and self.fecha_pago < self.fecha_emision
        ):
            raise ValueError("fecha_pago no puede ser anterior a fecha_emision.")
        return self


class ChequeUpdate(BaseModel):
    """Corrección de la carga de un cheque desde el panel.

    Todos los campos son opcionales: se aplican solo los presentes en el body
    (`exclude_unset`). Los campos que mueven plata (`monto`, `porcentaje_compra`,
    `porcentaje_venta`) recalculan ganancia/fiado/caja en el servicio. El servicio
    rechaza editar cheques en estado terminal (COBRADO/RECHAZADO) y fijar
    `porcentaje_venta`/`cliente_destino_id` en cheques que aún no se vendieron/fiaron.
    """

    nro_cheque: str | None = Field(default=None, min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    porcentaje_venta: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_origen_id: UUID | None = None
    cliente_destino_id: UUID | None = None


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
    porcentaje_venta: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class ChequeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    nro_cheque: str
    banco: str | None
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
    tiene_foto: bool
    created_at: datetime
    updated_at: datetime


class ChequeFiarResponse(BaseModel):
    cheque: ChequeRead
    fiado: FiadoRead


class FiadoCobrarConChequeResponse(BaseModel):
    fiado: FiadoRead
    cheque_ingresado: ChequeRead
    diferencia: Decimal
