"""drop deudas, add pasivos and gastos_operativos

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-08

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------
    # 1. Eliminar tabla deudas y sus ENUMs
    # ------------------------------------------------------------------
    op.drop_table("deudas")
    op.execute(sa.text("DROP TYPE IF EXISTS deuda_estado"))
    op.execute(sa.text("DROP TYPE IF EXISTS deuda_tipo"))

    # ------------------------------------------------------------------
    # 2. ENUM nuevo para pasivos
    # ------------------------------------------------------------------
    postgresql.ENUM("pendiente", "cancelada", name="pasivo_estado").create(
        op.get_bind(), checkfirst=True
    )

    # ------------------------------------------------------------------
    # 3. Tabla: pasivos (deudas del negocio con terceros)
    # ------------------------------------------------------------------
    op.create_table(
        "pasivos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("acreedor", sa.String(200), nullable=False),
        sa.Column("concepto", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "moneda",
            postgresql.ENUM("ARS", "USD", name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "estado",
            postgresql.ENUM("pendiente", "cancelada", name="pasivo_estado", create_type=False),
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
        sa.CheckConstraint("monto > 0", name="ck_pasivos_monto_positive"),
    )
    op.create_index("ix_pasivos_estado", "pasivos", ["estado"])
    op.create_index("ix_pasivos_fecha_vencimiento", "pasivos", ["fecha_vencimiento"])
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_pasivos_updated_at
            BEFORE UPDATE ON pasivos
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )

    # ------------------------------------------------------------------
    # 4. Tabla: gastos_operativos
    # ------------------------------------------------------------------
    op.create_table(
        "gastos_operativos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("concepto", sa.String(300), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "moneda",
            postgresql.ENUM("ARS", "USD", name="moneda", create_type=False),
            nullable=False,
            server_default=sa.text("'ARS'"),
        ),
        sa.Column("fecha_operacion", sa.Date(), nullable=False),
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
        sa.CheckConstraint("monto > 0", name="ck_gastos_operativos_monto_positive"),
    )
    op.create_index("ix_gastos_operativos_fecha_operacion", "gastos_operativos", ["fecha_operacion"])
    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_gastos_operativos_updated_at
            BEFORE UPDATE ON gastos_operativos
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.drop_table("gastos_operativos")
    op.drop_table("pasivos")
    op.execute(sa.text("DROP TYPE IF EXISTS pasivo_estado"))

    # Recrear deudas
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
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_deudas_monto_positive"),
    )
