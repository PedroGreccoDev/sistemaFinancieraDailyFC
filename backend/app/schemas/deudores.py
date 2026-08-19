"""deudores.py — Cobro consolidado de la deuda de un cliente.

La pestaña "General" de Deudores no cobra una deuda: cobra **al cliente**. El
operador recibe la plata y no tiene por qué decidir si va contra el cheque que
le fió, contra la mercadería que le dio o contra la cuota del préstamo — el
importe se imputa de la operación más vieja a la más nueva, sin importar el tipo.

Los schemas de acá describen esa operación agregada; el reparto real vive en
`app.services.deudores`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.db.models import Moneda
from app.schemas.cheques import ChequeRead
# El vuelto de un cheque "de más" se resuelve igual que en pasivos (§5) y que en
# el cobro por cliente de deudas libres (§2.b): mismo tipo, mismo vocabulario.
from app.schemas.pasivos import VueltoModo


# Las tres fuentes de deuda de un cliente. Un módulo nuevo de deuda de cliente
# se da de alta acá y en `svc_deudores._cargar_renglones`.
RenglonTipo = Literal["fiado", "deuda_simple", "prestamo"]


class RenglonImputado(BaseModel):
    """Una deuda concreta alcanzada por el cobro, y cuánto le tocó.

    `detalle` es el texto que el operador ve en pantalla y en el chat ("Cheque
    fiado Nº 1234", el concepto de la deuda libre, "Préstamo 2/6 cuotas"), para
    que el resultado del cobro sea auditable renglón por renglón.
    """

    tipo: RenglonTipo
    id: UUID
    detalle: str
    fecha: date
    imputado: Decimal
    saldo_restante: Decimal
    cancelado: bool


class CobroClienteCreate(BaseModel):
    """Cobro de un importe libre contra **toda** la deuda de un cliente.

    `moneda_deuda` dice contra qué deudas se cobra: ARS y USD son cajas
    distintas y no se suman entre sí (los cheques fiados son siempre ARS, así
    que en USD solo entran deudas libres y préstamos en dólares).
    `monto_cobrado` es lo que entra a caja, en `moneda_pago`, que puede diferir;
    en ese caso `cotizacion` ($/USD) define cuánto del saldo queda saldado.
    """

    cliente_id: UUID
    moneda_deuda: Moneda
    monto_cobrado: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda_pago: Moneda
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha_cobro: date | None = None


class CobroClienteResponse(BaseModel):
    """Resultado del cobro consolidado.

    `renglones` son las deudas alcanzadas, en el orden en que se imputaron (la
    más vieja primero). `imputado` es cuánto bajó la deuda total y
    `saldo_restante` lo que el cliente sigue debiendo en esa moneda.
    """

    cliente_id: UUID
    cliente_nombre: str
    moneda_deuda: Moneda
    renglones: list[RenglonImputado]
    imputado: Decimal
    canceladas: int
    saldo_restante: Decimal


class CobroClienteChequeCreate(BaseModel):
    """Cobro de toda la deuda de un cliente con un solo cheque.

    El cheque salda por su **valor neto** (`monto × (1 − %compra)`), imputado de
    la operación más vieja a la más nueva igual que el efectivo, y **no asienta
    caja**: entra a cartera a nombre del cliente y la plata se reconoce recién
    al venderlo o cobrarlo.

    Un cheque que vale más que todo lo que el cliente debe es el caso normal —el
    cliente entrega el que tiene—, así que la diferencia queda a su favor y
    `vuelto_modo` decide qué se hace con ella (obligatorio solo si sobra).

    Los cheques son siempre en pesos: cobrar deuda en USD exige `cotizacion`.
    """

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


class CobroClienteChequeResponse(CobroClienteResponse):
    """Resultado del cobro consolidado con cheque.

    `vuelto_ars` va en **ARS** aunque las deudas sean en dólares —el excedente de
    un cheque es plata en pesos y en pesos se devuelve— y es > 0 solo cuando el
    cheque cubrió todo; `vuelto_modo` dice qué se hizo con él.
    """

    cheque_ingresado: ChequeRead
    vuelto_ars: Decimal
    vuelto_modo: VueltoModo | None = None


class RenglonPendiente(BaseModel):
    """Una deuda abierta del cliente, tal como entra al total consolidado."""

    tipo: RenglonTipo
    id: UUID
    detalle: str
    fecha: date
    saldo: Decimal


class DeudaClienteResumen(BaseModel):
    """Lo que un cliente debe en una moneda, con el detalle que lo compone.

    Es la lectura que consume el bot para contestar cuánto debe alguien sin
    tener que reconstruirlo de tres consultas distintas.
    """

    cliente_id: UUID
    cliente_nombre: str
    moneda: Moneda
    total: Decimal
    renglones: list[RenglonPendiente]
