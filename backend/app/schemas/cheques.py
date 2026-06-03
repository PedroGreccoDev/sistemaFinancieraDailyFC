from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

<<<<<<< HEAD
from pydantic import BaseModel, ConfigDict, Field
=======
import pydantic
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f

from app.db.models import ChequeEstado
from app.schemas.prestamos import PrestamoCreateFromCheque, PrestamoRead


<<<<<<< HEAD
class ChequeCreate(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None


class ChequeManualTransition(BaseModel):
    target_state: ChequeEstado
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    porcentaje_venta: Decimal | None = Field(
=======
class ChequeCreate(pydantic.BaseModel):
    nro_cheque: str = pydantic.Field(min_length=1, max_length=64)
    monto: Decimal = pydantic.Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = pydantic.Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None


class ChequeManualTransition(pydantic.BaseModel):
    target_state: ChequeEstado
    operador_id: str = pydantic.Field(min_length=1, max_length=80)
    motivo: str = pydantic.Field(min_length=1)
    porcentaje_venta: Decimal | None = pydantic.Field(
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_destino_id: UUID | None = None


<<<<<<< HEAD
class ChequeFiarRequest(BaseModel):
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
=======
class ChequeFiarRequest(pydantic.BaseModel):
    operador_id: str = pydantic.Field(min_length=1, max_length=80)
    motivo: str = pydantic.Field(min_length=1)
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
    cliente_destino_id: UUID
    prestamo: PrestamoCreateFromCheque


<<<<<<< HEAD
class ChequeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
=======
class ChequeRead(pydantic.BaseModel):
    model_config = pydantic.ConfigDict(from_attributes=True)
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f

    nro_cheque: str
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
    created_at: datetime
    updated_at: datetime


<<<<<<< HEAD
class ChequeFiarResponse(BaseModel):
=======
class ChequeFiarResponse(pydantic.BaseModel):
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
    cheque: ChequeRead
    prestamo: PrestamoRead

