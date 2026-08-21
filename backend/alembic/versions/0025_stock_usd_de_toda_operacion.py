"""Todo dólar que entra o sale mueve el stock, no solo la compra/venta

La caja USD y el stock vendible venían divergiendo. Solo tocaban lotes la
compra/venta de divisas (§4), la apertura (0019), los ajustes (0020) y el
préstamo recibido en dólares (0024). Quedaban afuera **cinco salidas** —otorgar
una deuda simple o un préstamo en USD, un gasto en USD, pagar un pasivo en USD—
y **tres entradas** —cobrar una cuota, un fiado o una deuda en USD—.

El efecto era en los dos sentidos y ninguno avisaba: los dólares que salían
seguían figurando como vendibles (y su costo se usaba para calcular la ganancia
de una venta futura que ya no tenía respaldo), y los que entraban no se podían
vender aunque estuvieran en la mano — la venta fallaba con "no hay stock".

El régimen ahora es simétrico y usa la pieza que ya existía: **todo movimiento de
stock que no es una compra/venta de divisas se representa como un
`MovimientoEfectivo` con `es_ajuste=True`** —la marca de "stock que se movió sin
una operación de divisas detrás", que no asienta caja ni figura en el listado de
Divisas—. Entra como COMPRA (aporta stock, al costo que **declara el operador**:
jamás se asume) y sale como VENTA (consume FIFO sin realizar ganancia, igual que
un ajuste que resta dólares).

`origen_tipo`/`origen_id` enlazan ese movimiento con la operación que lo generó,
para poder deshacerlo cuando esa operación se edita o se anula. Es el mismo par
que ya usan los pasivos para recordar de qué compra salieron (0021).

Revision ID: 0025
Revises: 0024
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movimientos_efectivo",
        sa.Column("origen_tipo", sa.String(40), nullable=True),
    )
    op.add_column(
        "movimientos_efectivo",
        sa.Column("origen_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Se busca por el par al deshacer una operación (borrar su movimiento de
    # stock), nunca por `origen_id` suelto.
    op.create_index(
        "ix_movimientos_efectivo_origen",
        "movimientos_efectivo",
        ["origen_tipo", "origen_id"],
    )

    # La cotización a la que entra cada dólar cobrado NO se guarda en la entidad
    # cobrada: vive en `cotizacion_aplicada` del propio movimiento de stock, que
    # es lo que el FIFO lee. Un fiado puede recibir tres cobros en USD a tres
    # cotizaciones distintas, y una columna en la tabla solo podría recordar una.


def downgrade() -> None:
    op.drop_index("ix_movimientos_efectivo_origen", table_name="movimientos_efectivo")
    op.drop_column("movimientos_efectivo", "origen_id")
    op.drop_column("movimientos_efectivo", "origen_tipo")
