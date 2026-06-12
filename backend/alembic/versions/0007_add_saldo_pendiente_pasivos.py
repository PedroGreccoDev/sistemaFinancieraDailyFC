"""Add saldo_pendiente to pasivos

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-11
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Agregar nullable primero para poder poblar filas existentes
    op.add_column("pasivos", sa.Column("saldo_pendiente", sa.Numeric(18, 2), nullable=True))
    # Inicializar con monto en registros existentes
    op.execute("UPDATE pasivos SET saldo_pendiente = monto WHERE estado = 'PENDIENTE'")
    op.execute("UPDATE pasivos SET saldo_pendiente = 0 WHERE estado = 'CANCELADA'")
    # Hacer NOT NULL
    op.alter_column("pasivos", "saldo_pendiente", nullable=False)
    op.create_check_constraint(
        "ck_pasivos_saldo_non_negative", "pasivos", "saldo_pendiente >= 0"
    )


def downgrade() -> None:
    op.drop_constraint("ck_pasivos_saldo_non_negative", "pasivos", type_="check")
    op.drop_column("pasivos", "saldo_pendiente")
