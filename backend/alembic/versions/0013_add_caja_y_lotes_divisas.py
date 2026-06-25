"""Add movimientos_caja + usd_restante (lotes FIFO de divisas)

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


caja_tipo = postgresql.ENUM("INGRESO", "EGRESO", name="caja_tipo")
caja_categoria = postgresql.ENUM(
    "COBRO_CUOTA",
    "COBRO_FIADO",
    "VENTA_CHEQUE",
    "COBRO_CHEQUE",
    "COMPRA_CHEQUE",
    "COMPRA_USD",
    "VENTA_USD",
    "OTORGAMIENTO_PRESTAMO",
    "GASTO",
    "PAGO_PASIVO",
    "VUELTO_PASIVO",
    name="caja_categoria",
)


def upgrade() -> None:
    bind = op.get_bind()

    # ── Lotes FIFO de divisas ────────────────────────────────────────────
    # Stock de USD no consumido por operación de compra. Arranca en 0 para las
    # filas existentes: el nuevo libro de caja parte limpio (solo de ahora en
    # adelante). Las compras nuevas setean usd_restante = monto desde el servicio.
    op.add_column(
        "movimientos_efectivo",
        sa.Column("usd_restante", sa.Numeric(18, 2), nullable=False, server_default="0"),
    )

    # ── Libro de caja ────────────────────────────────────────────────────
    caja_tipo.create(bind, checkfirst=True)
    caja_categoria.create(bind, checkfirst=True)

    op.create_table(
        "movimientos_caja",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("moneda", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        sa.Column("tipo", postgresql.ENUM(name="caja_tipo", create_type=False), nullable=False),
        sa.Column("categoria", postgresql.ENUM(name="caja_categoria", create_type=False), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("ganancia", sa.Numeric(18, 2), nullable=True),
        sa.Column("referencia_tipo", sa.String(length=40), nullable=True),
        sa.Column("referencia_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("detalle", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_movimientos_caja_monto_positive"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movimientos_caja_fecha", "movimientos_caja", ["fecha"])
    op.create_index("ix_movimientos_caja_moneda", "movimientos_caja", ["moneda"])
    op.create_index("ix_movimientos_caja_tipo", "movimientos_caja", ["tipo"])
    op.create_index("ix_movimientos_caja_categoria", "movimientos_caja", ["categoria"])
    op.create_index("ix_movimientos_caja_moneda_fecha", "movimientos_caja", ["moneda", "fecha"])
    op.create_index("ix_movimientos_caja_referencia_id", "movimientos_caja", ["referencia_id"])

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_movimientos_caja_updated_at
            BEFORE UPDATE ON movimientos_caja
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_movimientos_caja_updated_at ON movimientos_caja"))
    op.drop_index("ix_movimientos_caja_referencia_id", table_name="movimientos_caja")
    op.drop_index("ix_movimientos_caja_moneda_fecha", table_name="movimientos_caja")
    op.drop_index("ix_movimientos_caja_categoria", table_name="movimientos_caja")
    op.drop_index("ix_movimientos_caja_tipo", table_name="movimientos_caja")
    op.drop_index("ix_movimientos_caja_moneda", table_name="movimientos_caja")
    op.drop_index("ix_movimientos_caja_fecha", table_name="movimientos_caja")
    op.drop_table("movimientos_caja")

    bind = op.get_bind()
    caja_categoria.drop(bind, checkfirst=True)
    caja_tipo.drop(bind, checkfirst=True)

    op.drop_column("movimientos_efectivo", "usd_restante")
