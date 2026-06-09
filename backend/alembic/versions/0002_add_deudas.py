"""add deudas

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-08

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tipos ENUM nuevos
    postgresql.ENUM("a_cobrar", "a_pagar", name="deuda_tipo").create(
        op.get_bind(), checkfirst=True
    )
    postgresql.ENUM("pendiente", "cancelada", name="deuda_estado").create(
        op.get_bind(), checkfirst=True
    )

    op.create_table(
        "deudas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cliente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("concepto", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "moneda",
            postgresql.ENUM("ARS", "USD", name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "tipo",
            postgresql.ENUM("a_cobrar", "a_pagar", name="deuda_tipo", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "estado",
            postgresql.ENUM("pendiente", "cancelada", name="deuda_estado", create_type=False),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=True),
        sa.Column("fecha_cancelacion", sa.Date(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.CheckConstraint("monto > 0", name="ck_deudas_monto_positive"),
    )

    op.create_index("ix_deudas_cliente_id",       "deudas", ["cliente_id"])
    op.create_index("ix_deudas_tipo",              "deudas", ["tipo"])
    op.create_index("ix_deudas_estado",            "deudas", ["estado"])
    op.create_index("ix_deudas_fecha_vencimiento", "deudas", ["fecha_vencimiento"])

    # Trigger updated_at (reutiliza la función ya creada en 0001)
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_deudas_updated_at
            BEFORE UPDATE ON deudas
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.drop_table("deudas")
    op.execute(sa.text("DROP TYPE IF EXISTS deuda_estado"))
    op.execute(sa.text("DROP TYPE IF EXISTS deuda_tipo"))
