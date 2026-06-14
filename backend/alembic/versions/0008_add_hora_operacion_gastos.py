"""Add hora_operacion to gastos_operativos

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Hora local (Argentina) en que se registró el gasto. Nullable: los gastos
    # viejos no la tienen y se siguen mostrando solo con la fecha.
    op.add_column(
        "gastos_operativos",
        sa.Column("hora_operacion", sa.Time(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("gastos_operativos", "hora_operacion")
