from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import (
    CuotaEstado,
    FrecuenciaCuotas,
    MedioPago,
    Moneda,
    PrestamoEstado,
    PrestamoTipo,
)
from app.schemas.cheques import ChequeRead


class PrestamoBase(BaseModel):
    """Alta de un préstamo, en cualquiera de las dos modalidades (§Interés fijo).

    Los campos del cuadro de cuotas (`cuotas`, `frecuencia`, `total_a_cobrar`) y
    los del interés fijo (`monto_interes_fijo`, `dia_cobro`) son opcionales acá y
    obligatorios según el `tipo_prestamo`: el validador de abajo exige los que
    corresponden y rechaza los que sobran, para que una carga con la modalidad
    equivocada falle en el borde y no adentro del servicio.
    """

    tipo_prestamo: PrestamoTipo = PrestamoTipo.NORMAL
    credito: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    fecha_inicio: date | None = None
    # Por cuál de las dos cajas paralelas pasó la plata (§Caja paralela).
    medio_pago: MedioPago = MedioPago.EFECTIVO

    # ── Solo NORMAL ───────────────────────────────────────────────────
    cuotas: int | None = Field(default=None, gt=0)
    frecuencia: FrecuenciaCuotas | None = None
    total_a_cobrar: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)

    # ── Solo INTERES_FIJO ─────────────────────────────────────────────
    # El interés de UN período de 30 días, en plata (no un %).
    monto_interes_fijo: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=2
    )
    # La fecha de cobro que se fija al alta: ancla de los ciclos de 30 días. Si
    # no viene, el servicio toma un ciclo después de la entrega.
    dia_cobro: date | None = None

    @model_validator(mode="after")
    def validate_modalidad(self) -> PrestamoBase:
        if self.tipo_prestamo == PrestamoTipo.INTERES_FIJO:
            if self.monto_interes_fijo is None:
                raise ValueError("Un préstamo a interés fijo necesita monto_interes_fijo")
            if any(v is not None for v in (self.cuotas, self.frecuencia, self.total_a_cobrar)):
                raise ValueError(
                    "Un préstamo a interés fijo no lleva cuadro de cuotas "
                    "(cuotas / frecuencia / total_a_cobrar)"
                )
            return self

        faltan = [
            nombre
            for nombre, valor in (
                ("cuotas", self.cuotas),
                ("frecuencia", self.frecuencia),
                ("total_a_cobrar", self.total_a_cobrar),
            )
            if valor is None
        ]
        if faltan:
            raise ValueError(f"Faltan campos del cuadro de cuotas: {', '.join(faltan)}")
        if any(v is not None for v in (self.monto_interes_fijo, self.dia_cobro)):
            raise ValueError(
                "monto_interes_fijo y dia_cobro son solo del préstamo a interés fijo"
            )
        if self.total_a_cobrar < self.credito:
            raise ValueError("total_a_cobrar debe ser mayor o igual al credito")
        return self


class PrestamoCreate(PrestamoBase):
    cliente_id: UUID


class PrestamoCreateFromCheque(PrestamoBase):
    pass


class PrestamoUpdate(BaseModel):
    """Corrección de la carga de un préstamo desde el panel.

    Campos opcionales (`exclude_unset`). El servicio solo permite editar si NINGUNA
    cuota fue cobrada (el préstamo sigue ACTIVO e intacto); cambiar capital, total,
    cantidad de cuotas, frecuencia o fecha de inicio **regenera el cuadro de cuotas**
    y rehace el egreso de caja del otorgamiento.

    **Solo para la modalidad NORMAL.** Un préstamo a interés fijo no tiene cuadro
    que regenerar: se edita con `PATCH /prestamos/{id}/interes-fijo`."""

    credito: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda | None = None
    medio_pago: MedioPago | None = None
    cuotas: int | None = Field(default=None, gt=0)
    frecuencia: FrecuenciaCuotas | None = None
    total_a_cobrar: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    fecha_inicio: date | None = None


class CuotaRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    prestamo_id: UUID
    numero_cuota: int
    fecha_vencimiento: date
    monto: Decimal
    monto_pagado: Decimal
    estado: CuotaEstado
    fecha_cobro: date | None
    created_at: datetime
    updated_at: datetime


class PrestamoRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID
    tipo_prestamo: PrestamoTipo
    credito: Decimal
    moneda: Moneda
    # En INTERES_FIJO vale 0: no es "cero cuotas", es "no tiene cuadro". La
    # cantidad de períodos devengados se cuenta con `cuotas_detalle`.
    cuotas: int
    frecuencia: FrecuenciaCuotas
    # En INTERES_FIJO no se conoce al alta: arranca igual al capital y crece con
    # cada interés que se devenga.
    total_a_cobrar: Decimal
    ganancia: Decimal
    estado: PrestamoEstado
    fecha_inicio: date
    # Solo INTERES_FIJO; null en los préstamos normales.
    monto_interes_fijo: Decimal | None = None
    dia_cobro: date | None = None
    capital_pendiente: Decimal | None = None
    cuotas_detalle: list[CuotaRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


# ── Préstamo a interés fijo (§Interés fijo) ──────────────────────────────────

class InteresFijoOperacionBase(BaseModel):
    """Lo común a las tres operaciones que mueven plata en esta modalidad.

    Van siempre **en la moneda del préstamo**: el interés se pactó en ella y el
    capital se devuelve en lo que se prestó. Para un cobro que cruza monedas
    está el pago de importe libre (`POST /prestamos/{id}/pagar`), que solo salda
    interés."""

    # Por cuál de las dos cajas paralelas pasó la plata (§Caja paralela).
    medio_pago: MedioPago = MedioPago.EFECTIVO
    fecha_cobro: date | None = None
    # A cuánto entran al stock vendible los dólares cobrados (§Stock de dólares).
    # Obligatoria cuando el préstamo es en USD: sin costo declarado esos dólares
    # no se van a poder vender. En pesos no se usa.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )


class CobrarInteresRequest(InteresFijoOperacionBase):
    """Cobro del interés de uno o varios períodos.

    Sin `cuota_ids` cobra el **período vigente** (el último devengado); con
    `incluir_mora`, además todos los períodos viejos impagos, que se acumulan."""

    cuota_ids: list[UUID] | None = None
    incluir_mora: bool = False


class AbonarCapitalRequest(InteresFijoOperacionBase):
    """Devolución de capital, total o parcial. No toca el interés."""

    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class CancelarInteresFijoRequest(InteresFijoOperacionBase):
    """Liquidación: capital pendiente + interés del período vigente.

    El interés del ciclo en curso va completo aunque falten días (sin prorrateo).
    `incluir_mora` decide si la mora acumulada se salda junto; si queda afuera,
    el préstamo **no** pasa a CANCELADO —esa deuda se sigue debiendo—."""

    incluir_mora: bool = True


class InteresFijoUpdate(BaseModel):
    """Renegociación del interés pactado.

    El nuevo valor rige de los próximos períodos en adelante; lo ya devengado
    quedó congelado. `aplicar_a_periodo_vigente` lo lleva también al ciclo en
    curso, y solo se permite si ese período todavía no recibió ni un peso.

    `dia_cobro` solo se puede mover **antes del primer período**: es el ancla de
    los ciclos y cambiarla después correría todas las fechas."""

    monto_interes_fijo: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=2
    )
    dia_cobro: date | None = None
    aplicar_a_periodo_vigente: bool = False


class CuotaCobroRequest(BaseModel):
    fecha_cobro: date | None = None
    # Por cuál de las dos cajas paralelas pasó la plata (§Caja paralela).
    medio_pago: MedioPago = MedioPago.EFECTIVO
    # A cuánto entran al stock vendible los dólares cobrados (§Stock de dólares).
    # Obligatoria cuando el préstamo es en USD: esa cuota hace entrar dólares y sin
    # costo declarado no se van a poder vender. En pesos no se usa.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )


class PrestamoPagoRequest(BaseModel):
    """Pago de importe libre (parcial o total) contra un préstamo, en efectivo.

    El operador paga `monto_pagado` en `moneda_pago` (lo que entra a caja). El
    importe se imputa a las cuotas más viejas primero (llenando cada una). Si la
    moneda de pago difiere de la del préstamo, `cotizacion` ($/USD) es obligatoria
    y define cuánto del préstamo (en su moneda) queda saldado.
    """

    monto_pagado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    # Por cuál de las dos cajas paralelas pasó la plata (§Caja paralela).
    medio_pago: MedioPago = MedioPago.EFECTIVO
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    # A cuánto entran al stock vendible los dólares cobrados (§Stock de dólares).
    # Obligatoria al cobrar en USD **un préstamo que también es en USD**: ahí no
    # hay `cotizacion` de la que sacar el costo, y sin costo esos dólares no se
    # pueden vender. Cuando el pago cruza monedas, la `cotizacion` ya sirve.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )
    fecha_cobro: date | None = None


class CuotaCobrarConChequeRequest(BaseModel):
    nro_cheque: str = Field(min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    cliente_origen_id: UUID | None = None
    fecha_cobro: date | None = None


class CuotaCobrarConChequeResponse(BaseModel):
    cuota: CuotaRead
    cheque: ChequeRead


class CuotasLoteCobrarRequest(BaseModel):
    cuota_ids: list[UUID] = Field(min_length=1)
    fecha_cobro: date | None = None
    # Por cuál de las dos cajas paralelas pasó la plata (§Caja paralela).
    medio_pago: MedioPago = MedioPago.EFECTIVO
    # Costo de entrada al stock de los dólares cobrados; ver CuotaCobroRequest.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )


class CuotasLoteCobrarConChequeRequest(BaseModel):
    cuota_ids: list[UUID] = Field(min_length=1)
    nro_cheque: str = Field(min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    cliente_origen_id: UUID | None = None
    fecha_cobro: date | None = None


class CuotasLoteCobrarConChequeResponse(BaseModel):
    cuotas: list[CuotaRead]
    cheque: ChequeRead
