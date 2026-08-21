from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import DeudaSimpleEstado, Moneda
from app.schemas.cheques import ChequeRead
# El vuelto de un cheque "de más" se resuelve igual que en pasivos (§5): o se
# paga en efectivo, o el negocio queda debiendo. Se reusa el mismo tipo para que
# no aparezcan dos vocabularios para la misma decisión.
from app.schemas.pasivos import VueltoModo


class DeudaSimpleCreate(BaseModel):
    """Alta de una deuda libre de un cliente (sin cuotas ni cheque).

    Registrarla saca la plata de la caja (EGRESO en `moneda`, con fecha `fecha`).
    """

    cliente_id: UUID
    concepto: str = Field(min_length=1)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    fecha: date | None = None
    observaciones: str | None = None


class DeudaSimpleUpdate(BaseModel):
    """Corrección de la carga de una deuda libre desde el panel.

    Campos opcionales (`exclude_unset`). `concepto`, `fecha` y `observaciones` se
    editan siempre. `monto`/`moneda` solo si está ABIERTA y sin cobros parciales
    (saldo == monto); el servicio recalcula el saldo y resincroniza el egreso."""

    concepto: str | None = Field(default=None, min_length=1)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda | None = None
    fecha: date | None = None
    observaciones: str | None = None


class DeudaSimplePagoRequest(BaseModel):
    """Cobro de una deuda libre (total o parcial), en efectivo.

    `monto_cobrado` es lo que entra a caja, en `moneda_pago` (que puede diferir de
    la moneda de la deuda). `cotizacion` ($/USD) es obligatoria solo cuando
    `moneda_pago` ≠ moneda de la deuda; imputa cuánto del saldo queda saldado."""

    monto_cobrado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    # A cuánto entran al stock vendible los dólares cobrados (§Stock de dólares).
    # Obligatoria al cobrar en USD **una deuda que también es en USD**: ahí no hay
    # `cotizacion` de la que sacar el costo, y sin costo esos dólares no se pueden
    # vender. Cuando el cobro cruza monedas, la `cotizacion` de arriba ya sirve.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )
    fecha_cobro: date | None = None


class DeudaSimpleCobroClienteCreate(BaseModel):
    """Cobro de un importe libre contra todas las deudas abiertas de un cliente.

    Es el cobro de la fila del cliente en "Otras deudas": el importe se imputa a
    las deudas de la más vieja a la más nueva, sin que el operador tenga que
    elegir a cuál va.

    `moneda_deuda` dice contra qué deudas se cobra: ARS y USD son cajas distintas
    y no se suman entre sí. `monto_cobrado` es lo que entra a caja, en
    `moneda_pago`, que puede diferir; en ese caso `cotizacion` ($/USD) imputa
    cuánto del saldo queda saldado."""

    cliente_id: UUID
    moneda_deuda: Moneda
    monto_cobrado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    # Costo de entrada al stock de los dólares cobrados; ver DeudaSimplePagoRequest.
    cotizacion_stock: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )
    fecha_cobro: date | None = None


class DeudaSimpleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    cliente_id: UUID
    concepto: str
    monto: Decimal
    saldo_pendiente: Decimal
    moneda: Moneda
    estado: DeudaSimpleEstado
    fecha: date
    fecha_cancelacion: date | None
    observaciones: str | None
    cotizacion_pago: Decimal | None
    created_at: datetime
    updated_at: datetime


class DeudaSimpleCobroClienteChequeCreate(BaseModel):
    """Cobro de TODAS las deudas abiertas de un cliente con un solo cheque.

    El cheque salda por su **valor neto** (`monto × (1 − %compra)`), imputado de
    la deuda más vieja a la más nueva. Un cheque que vale más que todo lo que el
    cliente debe es el caso normal —el cliente entrega el que tiene—, así que la
    diferencia queda a favor suyo y `vuelto_modo` decide qué se hace con ella
    (obligatorio solo si hay diferencia). Mismo mecanismo que el vuelto de un
    pasivo pagado con cheque de más (§5).

    Los cheques son siempre en pesos: cobrar deudas en USD exige `cotizacion`."""

    cliente_id: UUID
    moneda_deuda: Moneda
    nro_cheque_pago: str = Field(min_length=1, max_length=64)
    banco_pago: str | None = Field(default=None, max_length=120)
    monto_cheque: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra_cheque: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    vuelto_modo: VueltoModo | None = None
    fecha_cobro: date | None = None


class DeudaSimpleCobroClienteChequeResponse(BaseModel):
    """Resultado del cobro por cliente con cheque.

    `imputado` es cuánto bajó la deuda en total y `saldo_restante` lo que el
    cliente sigue debiendo, ambos en la moneda de las deudas. `vuelto_ars` va en
    **ARS** —el excedente de un cheque es plata en pesos— y es > 0 solo cuando el
    cheque cubrió todo; `vuelto_modo` dice qué se hizo con él.
    """

    deudas_afectadas: list[DeudaSimpleRead]
    cheque_ingresado: ChequeRead
    imputado: Decimal
    canceladas: int
    saldo_restante: Decimal
    vuelto_ars: Decimal
    vuelto_modo: VueltoModo | None = None


class DeudaSimpleCobroClienteResponse(BaseModel):
    """Resultado del cobro por cliente.

    `deudas_afectadas` son las deudas que recibieron parte del importe, en el
    orden en que se imputaron (la más vieja primero). `imputado` es cuánto bajó
    la deuda en total y `saldo_restante` lo que el cliente sigue debiendo, ambos
    en la moneda de las deudas.
    """

    deudas_afectadas: list[DeudaSimpleRead]
    imputado: Decimal
    canceladas: int
    saldo_restante: Decimal


class DeudaSimpleCobrarConChequeRequest(BaseModel):
    """Cobro de una deuda libre entregando un cheque en vez de efectivo.

    El cheque entra a cartera a nombre del cliente de la deuda y vale su
    `valor_neto = monto_cheque × (1 − porcentaje_compra_cheque / 100)`.

    Los cheques son SIEMPRE en pesos, así que cobrar con cheque una deuda en USD
    cruza monedas y exige `cotizacion` ($/USD) — igual que el cobro en efectivo.
    """

    nro_cheque_pago: str = Field(min_length=1, max_length=64)
    banco_pago: str | None = Field(default=None, max_length=120)
    monto_cheque: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra_cheque: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    # Obligatoria solo si la deuda es en USD (el cheque siempre entra en ARS).
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    # Obligatorio solo si el cheque cubre de más: qué se hace con el excedente.
    # Mismo criterio que el cobro por cliente y que el vuelto de un pasivo (§5).
    vuelto_modo: VueltoModo | None = None
    fecha_cobro: date | None = None


class DeudaSimpleCobrarConChequeResponse(BaseModel):
    """Resultado del cobro con cheque.

    `diferencia` en la moneda de la deuda: > 0 el cheque valía más que el saldo y
    el negocio le queda debiendo esa diferencia al cliente; < 0 el cliente todavía
    debe el resto; 0 justo.

    `vuelto_ars` es esa misma diferencia positiva llevada a **pesos** (el
    excedente de un cheque es plata en pesos y en pesos se devuelve), y
    `vuelto_modo` dice qué se hizo con ella: pagarla o quedar debiéndola.
    """

    deuda: DeudaSimpleRead
    cheque_ingresado: ChequeRead
    diferencia: Decimal
    vuelto_ars: Decimal
    vuelto_modo: VueltoModo | None = None
