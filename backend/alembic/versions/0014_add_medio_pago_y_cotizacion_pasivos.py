"""Add medio_pago + cotizacion a movimientos_caja y cotizacion_pago a pasivos

Soporta el pago de deudas por efectivo/transferencia y en moneda distinta a la
de la deuda (con cotización por pago). Todas las columnas nuevas son nullable y
no requieren backfill: las filas existentes quedan en NULL.

Revision ID: 0014
Revises: 0013
Create Date: 2026-06-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


medio_pago = postgresql.ENUM("EFECTIVO", "TRANSFERENCIA", name="medio_pago")


def upgrade() -> None:
    bind = op.get_bind()
    medio_pago.create(bind, checkfirst=True)

    op.add_column(
        "movimientos_caja",
        sa.Column(
            "medio_pago",
            postgresql.ENUM(name="medio_pago", create_type=False),
            nullable=True,
        ),
    )
    op.add_column(
        "movimientos_caja",
        sa.Column("cotizacion", sa.Numeric(18, 4), nullable=True),
    )
    op.add_column(
        "pasivos",
        sa.Column("cotizacion_pago", sa.Numeric(18, 4), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pasivos", "cotizacion_pago")
    op.drop_column("movimientos_caja", "cotizacion")
    op.drop_column("movimientos_caja", "medio_pago")

    bind = op.get_bind()
    medio_pago.drop(bind, checkfirst=True)
