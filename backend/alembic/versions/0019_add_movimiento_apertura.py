"""Lote de dólares de apertura (stock inicial sin movimiento de caja)

El `saldo_inicial_usd` da el **efectivo** en la caja USD, pero no crea **stock**:
la venta de divisas consume lotes `MovimientoEfectivo` de tipo COMPRA (§4), así
que sin un lote el negocio no puede vender los dólares que tiene, aunque el saldo
diga que están.

Esta marca distingue ese lote de apertura de una compra real: existe para aportar
stock con su costo promedio, pero **no asienta caja** — esos pesos salieron antes
de que el sistema existiera, igual que con la cartera de cheques preexistente.

Revision ID: 0019
Revises: 0018
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "movimientos_efectivo",
        sa.Column("es_apertura", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    # Cotización promedio a la que se consiguió el stock inicial de dólares.
    op.add_column(
        "configuracion_apertura",
        sa.Column("cotizacion_usd_inicial", sa.Numeric(18, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("configuracion_apertura", "cotizacion_usd_inicial")
    op.drop_column("movimientos_efectivo", "es_apertura")
