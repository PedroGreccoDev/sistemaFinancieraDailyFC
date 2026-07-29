"""Add deudas_simples (deuda libre de cliente, sin cuotas ni cheque)

Nueva cuenta por cobrar: al registrarla sale un EGRESO de caja (OTORGAMIENTO_DEUDA)
y al cobrarla entra un INGRESO (COBRO_DEUDA), total o parcial y cross-currency. Se
agregan esos dos valores al enum `caja_categoria` y un enum propio de estado.

Revision ID: 0016
Revises: 0015
Create Date: 2026-07-18
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0016"
down_revision: Union[str, None] = "0015"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


deuda_simple_estado = postgresql.ENUM("ABIERTA", "CANCELADA", name="deuda_simple_estado")


def upgrade() -> None:
    bind = op.get_bind()

    # Nuevos valores del enum de categorías de caja (idempotente). ADD VALUE no
    # se puede usar en la misma transacción en que se agrega, pero acá solo se
    # declara: las filas nuevas los usan desde el servicio, en otra transacción.
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'OTORGAMIENTO_DEUDA'")
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'COBRO_DEUDA'")

    deuda_simple_estado.create(bind, checkfirst=True)

    op.create_table(
        "deudas_simples",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concepto", sa.Text(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("saldo_pendiente", sa.Numeric(18, 2), nullable=False),
        sa.Column("moneda", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(name="deuda_simple_estado", create_type=False),
            nullable=False,
            server_default="ABIERTA",
        ),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("fecha_cancelacion", sa.Date(), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("cotizacion_pago", sa.Numeric(18, 4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0",           name="ck_deudas_simples_monto_positive"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_deudas_simples_saldo_non_negative"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_deudas_simples_cliente_id", "deudas_simples", ["cliente_id"])
    op.create_index("ix_deudas_simples_estado",     "deudas_simples", ["estado"])

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_deudas_simples_updated_at
            BEFORE UPDATE ON deudas_simples
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_deudas_simples_updated_at ON deudas_simples"))
    op.drop_index("ix_deudas_simples_estado",     table_name="deudas_simples")
    op.drop_index("ix_deudas_simples_cliente_id", table_name="deudas_simples")
    op.drop_table("deudas_simples")

    bind = op.get_bind()
    deuda_simple_estado.drop(bind, checkfirst=True)

    # Nota: no se quitan los valores agregados al enum caja_categoria: PostgreSQL
    # no soporta DROP VALUE en un enum. Quedan como valores no usados si se baja.
