"""Add fiados table

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-09
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


fiado_estado = postgresql.ENUM("ABIERTO", "CANCELADO", name="fiado_estado")


def upgrade() -> None:
    bind = op.get_bind()
    fiado_estado.create(bind, checkfirst=True)

    op.create_table(
        "fiados",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cheque_nro", sa.String(length=64), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monto_original", sa.Numeric(18, 2), nullable=False),
        sa.Column("porcentaje_venta", sa.Numeric(7, 4), nullable=False),
        sa.Column("saldo_pendiente", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(name="fiado_estado", create_type=False),
            nullable=False,
            server_default="ABIERTO",
        ),
        sa.Column("fecha_fiado", sa.Date(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("monto_original > 0",   name="ck_fiados_monto_positive"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_fiados_saldo_non_negative"),
        sa.CheckConstraint(
            "porcentaje_venta >= 0 AND porcentaje_venta <= 100",
            name="ck_fiados_porcentaje_range",
        ),
        sa.ForeignKeyConstraint(["cheque_nro"], ["cheques.nro_cheque"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"],        ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cheque_nro", name="uq_fiados_cheque_nro"),
    )
    op.create_index("ix_fiados_cheque_nro", "fiados", ["cheque_nro"])
    op.create_index("ix_fiados_cliente_id", "fiados", ["cliente_id"])
    op.create_index("ix_fiados_estado",     "fiados", ["estado"])


def downgrade() -> None:
    op.drop_index("ix_fiados_estado",     table_name="fiados")
    op.drop_index("ix_fiados_cliente_id", table_name="fiados")
    op.drop_index("ix_fiados_cheque_nro", table_name="fiados")
    op.drop_table("fiados")

    bind = op.get_bind()
    fiado_estado.drop(bind, checkfirst=True)
