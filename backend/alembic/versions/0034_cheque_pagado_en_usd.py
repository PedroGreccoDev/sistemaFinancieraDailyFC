"""El cheque que se le paga al cliente en dólares

Hasta acá comprar un cheque sacaba pesos y nada más: el valor neto salía entero
de la caja ARS, o quedaba a deber. Pero el negocio también paga con dólares
—"te lo compro al 10,2%, te doy 4200 a 1555 y el resto en efectivo"—, y esa
operación no se podía cargar. Lo que se hacía era anotarla como si hubiera
salido todo en pesos: la caja de dólares quedaba alta por lo que se entregó y la
de pesos baja por lo mismo, dos descuadres de una que recién aparecen al cerrar.

Dos columnas, las dos NULL en todo lo ya cargado —que es exactamente lo que
significan: esa compra no entregó un dólar—:

  - `usd_entregados`: los dólares que se le dieron al cliente.
  - `cotizacion_usd`: a cuánto se los tomaron, en pesos por dólar. **La dicta el
    operador siempre** (regla 1 del bot, §4): el sistema no la asume ni la
    consulta a ningún lado.

Lo que cubren esos dólares es `usd_entregados × cotizacion_usd` en pesos, y
`monto_abonado` sigue significando lo mismo que siempre: los **pesos** que
salieron de la caja. Entre los dos tienen que llegar al valor neto del cheque; lo
que falte queda a deber con el vendedor, igual que antes.

Van juntas o no va ninguna (`ck_cheques_usd_completo`): un cheque con dólares y
sin cotización no se podría valuar —no habría con qué saber cuántos pesos
cubrieron— y uno con cotización y sin dólares no significa nada. Las dos
positivas cuando están: entregar 0 dólares es no entregar ninguno.

Los dólares salen del stock consumiendo lotes FIFO, sin realizar ganancia
_(decisión del dueño, 2026-09-21)_: son dólares que se fueron, y lo que se ganó
con ellos queda dentro de la ganancia del cheque cuando se venda. Eso no necesita
columna —lo lleva el `MovimientoEfectivo` de salida, con `origen_tipo='cheque'`—
pero es la razón por la que acá no hay ninguna columna de ganancia.

Revision ID: 0034
Revises: 0033
Create Date: 2026-09-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0034"
down_revision: Union[str, None] = "0033"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cheques",
        sa.Column("usd_entregados", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "cheques",
        sa.Column("cotizacion_usd", sa.Numeric(18, 6), nullable=True),
    )
    op.create_check_constraint(
        "ck_cheques_usd_completo",
        "cheques",
        "(usd_entregados IS NULL AND cotizacion_usd IS NULL) OR "
        "(usd_entregados > 0 AND cotizacion_usd > 0)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cheques_usd_completo", "cheques", type_="check")
    op.drop_column("cheques", "cotizacion_usd")
    op.drop_column("cheques", "usd_entregados")
