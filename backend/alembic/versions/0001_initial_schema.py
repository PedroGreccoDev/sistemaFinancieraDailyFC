"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-02

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_enum(name: str, *values: str) -> None:
    values_sql = ", ".join(f"'{v}'" for v in values)
    op.execute(sa.text(
        f"DO $$ BEGIN "
        f"IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = '{name}') THEN "
        f"CREATE TYPE {name} AS ENUM ({values_sql}); "
        f"END IF; "
        f"END $$;"
    ))


def _drop_enum(name: str) -> None:
    op.execute(sa.text(f"DROP TYPE IF EXISTS {name}"))


def _create_updated_at_trigger(table: str) -> None:
    """Agrega un trigger DB-level que mantiene updated_at al día."""
    op.execute(
        sa.text(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


# ---------------------------------------------------------------------------
# Upgrade
# ---------------------------------------------------------------------------

def upgrade() -> None:
    conn = op.get_bind()

    # ------------------------------------------------------------------
    # Función trigger reutilizable para updated_at
    # ------------------------------------------------------------------
    conn.execute(
        sa.text(
            """
            CREATE OR REPLACE FUNCTION fn_set_updated_at()
            RETURNS TRIGGER AS $$
            BEGIN
                NEW.updated_at = NOW();
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;
            """
        )
    )

    # ------------------------------------------------------------------
    # Tipos ENUM
    # ------------------------------------------------------------------
    _create_enum("cheque_estado", "EN_CARTERA", "VENDIDO", "FIADO", "COBRADO", "RECHAZADO")
    _create_enum("moneda", "ARS", "USD")
    _create_enum("prestamo_estado", "activo", "cancelado", "en_mora")
    _create_enum("cuota_estado", "pendiente", "cobrada", "en_mora")
    _create_enum("frecuencia_cuotas", "diaria", "semanal", "quincenal", "mensual", "anual")
    _create_enum("movimiento_efectivo_tipo", "compra", "venta")

    # ------------------------------------------------------------------
    # Tabla: clientes
    # ------------------------------------------------------------------
    op.create_table(
        "clientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("nombre", sa.String(160), nullable=False),
        sa.Column("cuit", sa.String(20), nullable=True),
        sa.Column("telefono", sa.String(40), nullable=True),
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
        sa.UniqueConstraint("cuit", name="uq_clientes_cuit"),
    )
    op.create_index("ix_clientes_nombre", "clientes", ["nombre"])
    _create_updated_at_trigger("clientes")

    # ------------------------------------------------------------------
    # Tabla: cheques
    # ------------------------------------------------------------------
    op.create_table(
        "cheques",
        sa.Column("nro_cheque", sa.String(64), primary_key=True),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("fecha_emision", sa.Date, nullable=True),
        sa.Column("fecha_pago", sa.Date, nullable=True),
        sa.Column("porcentaje_compra", sa.Numeric(7, 4), nullable=False),
        sa.Column("porcentaje_venta", sa.Numeric(7, 4), nullable=True),
        sa.Column(
            "ganancia",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "estado",
            sa.Enum(
                "EN_CARTERA", "VENDIDO", "FIADO", "COBRADO", "RECHAZADO",
                name="cheque_estado",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'EN_CARTERA'"),
        ),
        sa.Column("ultimo_evento_manual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_operador_id", sa.String(80), nullable=True),
        sa.Column("ultimo_motivo_manual", sa.Text, nullable=True),
        sa.Column(
            "cliente_origen_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "cliente_destino_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="SET NULL"),
            nullable=True,
        ),
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
        sa.CheckConstraint("monto > 0", name="ck_cheques_monto_positive"),
        sa.CheckConstraint(
            "porcentaje_compra >= 0 AND porcentaje_compra <= 100",
            name="ck_cheques_porcentaje_compra_range",
        ),
        sa.CheckConstraint(
            "porcentaje_venta IS NULL OR "
            "(porcentaje_venta >= 0 AND porcentaje_venta <= 100)",
            name="ck_cheques_porcentaje_venta_range",
        ),
        sa.CheckConstraint(
            "fecha_pago IS NULL OR fecha_emision IS NULL OR fecha_pago >= fecha_emision",
            name="ck_cheques_fecha_pago_after_emision",
        ),
    )
    op.create_index("ix_cheques_estado", "cheques", ["estado"])
    op.create_index("ix_cheques_cliente_origen_id", "cheques", ["cliente_origen_id"])
    op.create_index("ix_cheques_cliente_destino_id", "cheques", ["cliente_destino_id"])
    _create_updated_at_trigger("cheques")

    # ------------------------------------------------------------------
    # Tabla: prestamos
    # ------------------------------------------------------------------
    op.create_table(
        "prestamos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cliente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "cheque_origen_nro",
            sa.String(64),
            sa.ForeignKey("cheques.nro_cheque", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("credito", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "moneda",
            sa.Enum("ARS", "USD", name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column("cuotas", sa.Integer, nullable=False),
        sa.Column(
            "frecuencia",
            sa.Enum(
                "diaria", "semanal", "quincenal", "mensual", "anual",
                name="frecuencia_cuotas",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("total_a_cobrar", sa.Numeric(18, 2), nullable=False),
        sa.Column("ganancia", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            sa.Enum(
                "activo", "cancelado", "en_mora",
                name="prestamo_estado",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'activo'"),
        ),
        sa.Column("fecha_inicio", sa.Date, nullable=False),
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
        sa.CheckConstraint("credito > 0", name="ck_prestamos_credito_positive"),
        sa.CheckConstraint("cuotas > 0", name="ck_prestamos_cuotas_positive"),
        sa.CheckConstraint(
            "total_a_cobrar >= credito",
            name="ck_prestamos_total_a_cobrar_gte_credito",
        ),
    )
    op.create_index("ix_prestamos_cliente_id", "prestamos", ["cliente_id"])
    op.create_index("ix_prestamos_estado", "prestamos", ["estado"])
    _create_updated_at_trigger("prestamos")

    # ------------------------------------------------------------------
    # Tabla: cuotas
    # ------------------------------------------------------------------
    op.create_table(
        "cuotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "prestamo_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("prestamos.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("numero_cuota", sa.Integer, nullable=False),
        sa.Column("fecha_vencimiento", sa.Date, nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            sa.Enum(
                "pendiente", "cobrada", "en_mora",
                name="cuota_estado",
                create_type=False,
            ),
            nullable=False,
            server_default=sa.text("'pendiente'"),
        ),
        sa.Column("fecha_cobro", sa.Date, nullable=True),
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
        sa.UniqueConstraint(
            "prestamo_id", "numero_cuota", name="uq_cuotas_prestamo_numero"
        ),
        sa.CheckConstraint("numero_cuota > 0", name="ck_cuotas_numero_positive"),
        sa.CheckConstraint("monto > 0", name="ck_cuotas_monto_positive"),
    )
    op.create_index("ix_cuotas_prestamo_id", "cuotas", ["prestamo_id"])
    op.create_index("ix_cuotas_estado", "cuotas", ["estado"])
    op.create_index("ix_cuotas_fecha_vencimiento", "cuotas", ["fecha_vencimiento"])
    _create_updated_at_trigger("cuotas")

    # ------------------------------------------------------------------
    # Tabla: movimientos_efectivo
    # ------------------------------------------------------------------
    op.create_table(
        "movimientos_efectivo",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "cliente_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clientes.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column(
            "tipo",
            sa.Enum("compra", "venta", name="movimiento_efectivo_tipo", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "moneda",
            sa.Enum("ARS", "USD", name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("cotizacion_aplicada", sa.Numeric(18, 6), nullable=False),
        sa.Column(
            "ganancia",
            sa.Numeric(18, 2),
            nullable=False,
            server_default=sa.text("0.00"),
        ),
        sa.Column(
            "fecha_operacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.Column("observaciones", sa.Text, nullable=True),
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
        sa.CheckConstraint(
            "monto > 0", name="ck_movimientos_efectivo_monto_positive"
        ),
        sa.CheckConstraint(
            "cotizacion_aplicada > 0",
            name="ck_movimientos_efectivo_cotizacion_positive",
        ),
    )
    op.create_index(
        "ix_movimientos_efectivo_tipo", "movimientos_efectivo", ["tipo"]
    )
    op.create_index(
        "ix_movimientos_efectivo_moneda", "movimientos_efectivo", ["moneda"]
    )
    op.create_index(
        "ix_movimientos_efectivo_fecha_operacion",
        "movimientos_efectivo",
        ["fecha_operacion"],
    )
    _create_updated_at_trigger("movimientos_efectivo")


# ---------------------------------------------------------------------------
# Downgrade
# ---------------------------------------------------------------------------

def downgrade() -> None:
    # Tablas en orden inverso a FK
    op.drop_table("movimientos_efectivo")
    op.drop_table("cuotas")
    op.drop_table("prestamos")
    op.drop_table("cheques")
    op.drop_table("clientes")

    # Tipos ENUM
    _drop_enum("movimiento_efectivo_tipo")
    _drop_enum("frecuencia_cuotas")
    _drop_enum("cuota_estado")
    _drop_enum("prestamo_estado")
    _drop_enum("moneda")
    _drop_enum("cheque_estado")

    # Función trigger
    op.execute(sa.text("DROP FUNCTION IF EXISTS fn_set_updated_at"))
