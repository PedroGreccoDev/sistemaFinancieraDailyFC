"""compensaciones.py — Saldar la deuda de un cliente contra una del negocio.

El negocio le debe a Y y X le debe al negocio. En vez de cobrarle a X y después
pagarle a Y, **X le transfiere directo a Y**: bajan las dos deudas y por la caja
del negocio no pasa un peso.

Los schemas describen esa operación; el reparto vive en
`app.services.compensaciones`, que reusa la imputación FIFO del cobro
consolidado (§2.c) en vez de duplicarla.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.db.models import Moneda
from app.schemas.deudores import RenglonImputado


class CompensacionCreate(BaseModel):
    """Una transferencia del cliente a un acreedor del negocio.

    `monto` y `moneda` son lo que **realmente se transfirió**: el hecho de la
    operación. De ahí salen las dos imputaciones —cuánto baja lo que el cliente
    debe y cuánto baja lo que el negocio le debe al acreedor—, cada una en su
    propia moneda y con la `cotizacion` que dicta el operador si alguna cruza.

    `moneda_deuda` dice contra qué deudas del cliente se imputa y `moneda_pasivo`
    contra cuáles del acreedor: ARS y USD son cajas distintas y no se suman (los
    cheques fiados son siempre ARS).
    """

    cliente_id: UUID
    # A quién le transfirió. Es el nombre del acreedor, no el id de una deuda: la
    # transferencia se reparte entre TODAS las deudas que el negocio le tiene, de
    # la más vieja a la más nueva. Quien resuelve un nombre parcial es quien
    # llama (el bot); acá tiene que llegar exacto.
    acreedor: str = Field(min_length=1, max_length=200)
    # Contra qué moneda de las deudas con ese acreedor imputa.
    moneda_pasivo: Moneda
    moneda_deuda: Moneda
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    moneda: Moneda
    cotizacion: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    fecha: date | None = None
    observaciones: str | None = None


class CompensacionResponse(BaseModel):
    """Resultado: qué quedó saldado de cada lado.

    `renglones` son las deudas del cliente alcanzadas, de la más vieja a la más
    nueva. Del lado del acreedor no van renglón por renglón porque el operador
    piensa en "lo que le debo a Pedro", no en cada compra: alcanza con cuánto
    bajó, cuánto queda y cuántas deudas se saldaron.

    `excedente` es lo que el cliente transfirió de más sobre lo que debía: le
    queda a favor como deuda del negocio con él (mismo criterio que el vuelto de
    un cheque, §5), en la moneda en que transfirió.
    """

    id: UUID
    fecha: date
    cliente_id: UUID
    cliente_nombre: str
    acreedor: str
    moneda: Moneda
    monto: Decimal
    moneda_deuda: Moneda
    moneda_pasivo: Moneda
    # Lado del cliente.
    renglones: list[RenglonImputado]
    imputado_cliente: Decimal
    canceladas: int
    saldo_restante_cliente: Decimal
    # Lado del acreedor: cuánto bajó en total lo que se le debe, qué queda y
    # cuántas de sus deudas quedaron saldadas por esta transferencia.
    imputado_pasivo: Decimal
    saldo_restante_pasivo: Decimal
    pasivos_cancelados: int
    # Excedente a favor del cliente, si transfirió de más.
    excedente: Decimal
    pasivo_excedente_id: UUID | None = None


class CompensacionRead(BaseModel):
    """Una compensación ya registrada, para listarla en el panel."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    fecha: date
    cliente_id: UUID
    acreedor: str
    moneda: Moneda
    monto: Decimal
    moneda_deuda: Moneda
    moneda_pasivo: Moneda
    cotizacion: Decimal | None
    imputado_cliente: Decimal
    imputado_pasivo: Decimal
    excedente: Decimal
    pasivo_excedente_id: UUID | None
    observaciones: str | None
    created_at: datetime
