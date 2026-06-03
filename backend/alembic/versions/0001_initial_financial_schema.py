"""Initial financial schema

Revision ID: 0001_initial_financial_schema
Revises: 
Create Date: 2026-06-02
"""

from __future__ import annotations

from typing import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0001_initial_financial_schema"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


cheque_estado = postgresql.ENUM(
    "EN_CARTERA",
    "VENDIDO",
    "FIADO",
    "COBRADO",
    "RECHAZADO",
    name="cheque_estado",
)
moneda = postgresql.ENUM("ARS", "USD", name="moneda")
prestamo_estado = postgresql.ENUM(
    "activo",
    "cancelado",
    "en_mora",
    name="prestamo_estado",
)
frecuencia_cuotas = postgresql.ENUM(
    "diaria",
    "semanal",
    "quincenal",
    "mensual",
    "anual",
    name="frecuencia_cuotas",
)
cuota_estado = postgresql.ENUM(
    "pendiente",
    "cobrada",
    "en_mora",
    name="cuota_estado",
)
movimiento_efectivo_tipo = postgresql.ENUM(
    "compra",
    "venta",
    name="movimiento_efectivo_tipo",
)


def upgrade() -> None:
    bind = op.get_bind()
    cheque_estado.create(bind, checkfirst=True)
    moneda.create(bind, checkfirst=True)
    prestamo_estado.create(bind, checkfirst=True)
    frecuencia_cuotas.create(bind, checkfirst=True)
    cuota_estado.create(bind, checkfirst=True)
    movimiento_efectivo_tipo.create(bind, checkfirst=True)

    op.create_table(
        "clientes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("nombre", sa.String(length=160), nullable=False),
        sa.Column("cuit", sa.String(length=20), nullable=True),
        sa.Column("telefono", sa.String(length=40), nullable=True),
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
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cuit", name="uq_clientes_cuit"),
    )
    op.create_index("ix_clientes_nombre", "clientes", ["nombre"])

    op.create_table(
        "cheques",
        sa.Column("nro_cheque", sa.String(length=64), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("fecha_emision", sa.Date(), nullable=True),
        sa.Column("fecha_pago", sa.Date(), nullable=True),
        sa.Column("porcentaje_compra", sa.Numeric(7, 4), nullable=False),
        sa.Column("porcentaje_venta", sa.Numeric(7, 4), nullable=True),
        sa.Column("ganancia", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(name="cheque_estado", create_type=False),
            nullable=False,
        ),
        sa.Column("ultimo_evento_manual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ultimo_operador_id", sa.String(length=80), nullable=True),
        sa.Column("ultimo_motivo_manual", sa.Text(), nullable=True),
        sa.Column("cliente_origen_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cliente_destino_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.CheckConstraint("monto > 0", name="ck_cheques_monto_positive"),
        sa.CheckConstraint(
            "porcentaje_compra >= 0 AND porcentaje_compra <= 100",
            name="ck_cheques_porcentaje_compra_range",
        ),
        sa.CheckConstraint(
            "porcentaje_venta IS NULL OR (porcentaje_venta >= 0 AND porcentaje_venta <= 100)",
            name="ck_cheques_porcentaje_venta_range",
        ),
        sa.CheckConstraint(
            "fecha_pago IS NULL OR fecha_emision IS NULL OR fecha_pago >= fecha_emision",
            name="ck_cheques_fecha_pago_after_emision",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_destino_id"],
            ["clientes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["cliente_origen_id"],
            ["clientes.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("nro_cheque"),
    )
    op.create_index("ix_cheques_cliente_destino_id", "cheques", ["cliente_destino_id"])
    op.create_index("ix_cheques_cliente_origen_id", "cheques", ["cliente_origen_id"])
    op.create_index("ix_cheques_estado", "cheques", ["estado"])

    op.create_table(
        "prestamos",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cheque_origen_nro", sa.String(length=64), nullable=True),
        sa.Column("credito", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "moneda",
            postgresql.ENUM(name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column("cuotas", sa.Integer(), nullable=False),
        sa.Column(
            "frecuencia",
            postgresql.ENUM(name="frecuencia_cuotas", create_type=False),
            nullable=False,
        ),
        sa.Column("total_a_cobrar", sa.Numeric(18, 2), nullable=False),
        sa.Column("ganancia", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(name="prestamo_estado", create_type=False),
            nullable=False,
        ),
        sa.Column("fecha_inicio", sa.Date(), nullable=False),
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
        sa.CheckConstraint("credito > 0", name="ck_prestamos_credito_positive"),
        sa.CheckConstraint("cuotas > 0", name="ck_prestamos_cuotas_positive"),
        sa.CheckConstraint(
            "total_a_cobrar >= credito",
            name="ck_prestamos_total_a_cobrar_gte_credito",
        ),
        sa.ForeignKeyConstraint(["cheque_origen_nro"], ["cheques.nro_cheque"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_prestamos_cliente_id", "prestamos", ["cliente_id"])
    op.create_index("ix_prestamos_estado", "prestamos", ["estado"])

    op.create_table(
        "movimientos_efectivo",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "tipo",
            postgresql.ENUM(name="movimiento_efectivo_tipo", create_type=False),
            nullable=False,
        ),
        sa.Column(
            "moneda",
            postgresql.ENUM(name="moneda", create_type=False),
            nullable=False,
        ),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column("cotizacion_aplicada", sa.Numeric(18, 6), nullable=False),
        sa.Column("ganancia", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "fecha_operacion",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("observaciones", sa.Text(), nullable=True),
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
        sa.CheckConstraint("monto > 0", name="ck_movimientos_efectivo_monto_positive"),
        sa.CheckConstraint(
            "cotizacion_aplicada > 0",
            name="ck_movimientos_efectivo_cotizacion_positive",
        ),
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_movimientos_efectivo_fecha_operacion", "movimientos_efectivo", ["fecha_operacion"])
    op.create_index("ix_movimientos_efectivo_moneda", "movimientos_efectivo", ["moneda"])
    op.create_index("ix_movimientos_efectivo_tipo", "movimientos_efectivo", ["tipo"])

    op.create_table(
        "cuotas",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("prestamo_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("numero_cuota", sa.Integer(), nullable=False),
        sa.Column("fecha_vencimiento", sa.Date(), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        sa.Column(
            "estado",
            postgresql.ENUM(name="cuota_estado", create_type=False),
            nullable=False,
        ),
        sa.Column("fecha_cobro", sa.Date(), nullable=True),
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
        sa.CheckConstraint("monto > 0", name="ck_cuotas_monto_positive"),
        sa.CheckConstraint("numero_cuota > 0", name="ck_cuotas_numero_positive"),
        sa.ForeignKeyConstraint(["prestamo_id"], ["prestamos.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("prestamo_id", "numero_cuota", name="uq_cuotas_prestamo_numero"),
    )
    op.create_index("ix_cuotas_estado", "cuotas", ["estado"])
    op.create_index("ix_cuotas_fecha_vencimiento", "cuotas", ["fecha_vencimiento"])
    op.create_index("ix_cuotas_prestamo_id", "cuotas", ["prestamo_id"])


def downgrade() -> None:
    op.drop_index("ix_cuotas_prestamo_id", table_name="cuotas")
    op.drop_index("ix_cuotas_fecha_vencimiento", table_name="cuotas")
    op.drop_index("ix_cuotas_estado", table_name="cuotas")
    op.drop_table("cuotas")

    op.drop_index("ix_movimientos_efectivo_tipo", table_name="movimientos_efectivo")
    op.drop_index("ix_movimientos_efectivo_moneda", table_name="movimientos_efectivo")
    op.drop_index("ix_movimientos_efectivo_fecha_operacion", table_name="movimientos_efectivo")
    op.drop_table("movimientos_efectivo")

    op.drop_index("ix_prestamos_estado", table_name="prestamos")
    op.drop_index("ix_prestamos_cliente_id", table_name="prestamos")
    op.drop_table("prestamos")

    op.drop_index("ix_cheques_estado", table_name="cheques")
    op.drop_index("ix_cheques_cliente_origen_id", table_name="cheques")
    op.drop_index("ix_cheques_cliente_destino_id", table_name="cheques")
    op.drop_table("cheques")

    op.drop_index("ix_clientes_nombre", table_name="clientes")
    op.drop_table("clientes")

    bind = op.get_bind()
    movimiento_efectivo_tipo.drop(bind, checkfirst=True)
    cuota_estado.drop(bind, checkfirst=True)
    frecuencia_cuotas.drop(bind, checkfirst=True)
    prestamo_estado.drop(bind, checkfirst=True)
    moneda.drop(bind, checkfirst=True)
    cheque_estado.drop(bind, checkfirst=True)
