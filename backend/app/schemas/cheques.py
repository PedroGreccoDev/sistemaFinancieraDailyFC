from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ChequeEstado, ChequeTipo, MedioPago
from app.schemas.fiados import FiadoRead


class ChequeCreate(BaseModel):
    # Opcional: el comprobante de emisión de un e-cheq no trae número (§E-cheq).
    # Se carga sin él y se completa después; el bot avisa cuando falta.
    nro_cheque: str | None = Field(default=None, min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None
    # Papel o e-cheq. Etiqueta: entra a la misma cartera y suma al mismo total.
    # Default PAPEL porque es el caso normal y porque así ninguna carga existente
    # —ni un cliente viejo de la API— cambia de significado al agregarse el campo.
    tipo: ChequeTipo = ChequeTipo.PAPEL
    # Pesos efectivamente abonados por el cheque. None = se pagó todo, la operación
    # normal. Si es menor al valor neto (`monto × (1 − %compra)`), la diferencia
    # queda a deber: no sale de la caja y genera el pasivo con quien lo vendió
    # (§Comprar sin abonar).
    monto_abonado: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    # Por cuál de las dos cajas salió lo abonado (§Caja paralela). No es columna
    # del cheque: solo viaja hasta la línea de caja de la compra.
    medio_pago: MedioPago = MedioPago.EFECTIVO

    @model_validator(mode="after")
    def validate_fechas(self) -> "ChequeCreate":
        if (
            self.fecha_emision is not None
            and self.fecha_pago is not None
            and self.fecha_pago < self.fecha_emision
        ):
            raise ValueError("fecha_pago no puede ser anterior a fecha_emision.")
        return self

    @model_validator(mode="after")
    def validate_monto_abonado(self) -> "ChequeCreate":
        if self.monto_abonado is None:
            return self
        # Lo que se paga por un cheque es su valor neto, no el nominal: un cheque
        # de $1.000.000 al 10% se compra por $900.000, y eso es lo que se debe.
        neto = (
            self.monto * (Decimal("100") - self.porcentaje_compra) / Decimal("100")
        ).quantize(Decimal("0.01"))
        if self.monto_abonado > neto:
            raise ValueError(
                f"Abonaste ${self.monto_abonado} y el cheque se compra por ${neto} "
                f"(neto al {self.porcentaje_compra}%): no puede superar ese valor."
            )
        if self.monto_abonado < neto and self.cliente_origen_id is None:
            raise ValueError(
                "Un cheque comprado a deber necesita el vendedor: indicá a quién "
                "le quedás debiendo."
            )
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
    # Editable en cualquier estado no terminal: el tipo es una etiqueta y no mueve
    # plata, así que corregir un e-cheq cargado como papel no recalcula nada.
    tipo: ChequeTipo | None = None


class ChequeManualTransition(BaseModel):
    target_state: ChequeEstado
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    porcentaje_venta: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_destino_id: UUID | None = None
    # Por cuál de las dos cajas entró lo cobrado al vender o cobrar el cheque.
    medio_pago: MedioPago = MedioPago.EFECTIVO


class ChequeFiarRequest(BaseModel):
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    cliente_destino_id: UUID
    porcentaje_venta: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class ChequeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Puede faltar: un e-cheq cargado desde un comprobante de emisión no trae
    # número (§E-cheq). Si esto vuelve a ser `str`, FastAPI no falla solo en esa
    # fila: **rechaza la respuesta entera** y el listado de cartera devuelve 500
    # con un `ResponseValidationError`. Un solo cheque sin número deja la pantalla
    # en blanco, y el panel no muestra ningún error —solo un contador en cero—.
    nro_cheque: str | None
    banco: str | None
    monto: Decimal
    fecha_emision: date | None
    fecha_pago: date | None
    porcentaje_compra: Decimal
    # Cuánto se abonó al comprarlo. None = se pagó todo; menos que el valor neto
    # significa que hay un pasivo abierto con el vendedor (§Comprar sin abonar).
    monto_abonado: Decimal | None
    porcentaje_venta: Decimal | None
    ganancia: Decimal
    estado: ChequeEstado
    tipo: ChequeTipo
    ultimo_evento_manual_at: datetime | None
    ultimo_operador_id: str | None
    ultimo_motivo_manual: str | None
    cliente_origen_id: UUID | None
    cliente_destino_id: UUID | None
    tiene_foto: bool
    # Qué vuelta de este mismo papel por el negocio es esta fila (§Recompra). 1 = la
    # primera y única, que es el caso normal; 2 o más significa que el cheque se
    # vendió, siguió girando en plaza y el negocio lo volvió a comprar. Lo calcula
    # `list_cheques` en una sola consulta —no está en la tabla— y por eso vale 1
    # cuando el cheque llega por un endpoint que no lo computa.
    vuelta: int = 1
    created_at: datetime
    updated_at: datetime


class ChequeFiarResponse(BaseModel):
    cheque: ChequeRead
    fiado: FiadoRead


class FiadoCobrarConChequeResponse(BaseModel):
    fiado: FiadoRead
    cheque_ingresado: ChequeRead
    diferencia: Decimal
