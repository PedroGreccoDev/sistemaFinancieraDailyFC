"""Ajustes manuales de caja (agregar o restar efectivo a mano)

Hasta acá la caja solo se movía como consecuencia de una operación de negocio
(un cobro, un gasto, una compra). No había forma de corregir un descuadre contra
el efectivo real del cajón, ni de registrar que el dueño puso o sacó plata.

Un ajuste es una entidad propia —con motivo y descripción— y no una línea suelta
en el libro: así se puede auditar por qué se tocó la caja y anularlo con el mismo
motor que el resto (§Anulación).

**Dólares:** agregar USD a la caja no alcanza para poder venderlos —la venta
consume lotes FIFO (§4)—, por eso un ajuste que suma USD lleva su `cotizacion_usd`
y crea un lote marcado `es_ajuste`, igual que el lote de apertura de la 0019. Ese
lote NO asienta caja: la caja la aporta la propia línea del ajuste.

Revision ID: 0020
Revises: 0019
Create Date: 2026-08-10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0020"
down_revision: Union[str, None] = "0019"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ajuste_caja_motivo = postgresql.ENUM(
    "CORRECCION", "APORTE", "RETIRO", "OTRO", name="ajuste_caja_motivo"
)


def upgrade() -> None:
    bind = op.get_bind()

    # Categoría nueva del libro de caja (idempotente). ADD VALUE no se puede usar
    # en la misma transacción en que se agrega, pero acá solo se declara: las filas
    # nuevas la usan desde el servicio, en otra transacción.
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'AJUSTE_CAJA'")

    ajuste_caja_motivo.create(bind, checkfirst=True)

    # Distingue el lote de un ajuste de una compra real de dólares: aporta stock
    # con su costo, pero no asienta caja (la línea del ajuste ya la mueve).
    op.add_column(
        "movimientos_efectivo",
        sa.Column("es_ajuste", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        "ajustes_caja",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        sa.Column("moneda", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        # INGRESO suma efectivo a la caja, EGRESO lo resta. El monto es siempre
        # positivo: el signo lo da el tipo, igual que en el libro de caja.
        sa.Column("tipo", postgresql.ENUM(name="caja_tipo", create_type=False), nullable=False),
        sa.Column(
            "motivo",
            postgresql.ENUM(name="ajuste_caja_motivo", create_type=False),
            nullable=False,
        ),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        # Solo en ajustes que SUMAN USD: costo ($/USD) del lote FIFO que se crea.
        sa.Column("cotizacion_usd", sa.Numeric(18, 6), nullable=True),
        # Lote FIFO creado por este ajuste (si sumó dólares), para poder borrarlo
        # al anularlo. SET NULL y no CASCADE: si el lote desaparece el ajuste sigue
        # siendo un hecho histórico que hay que poder auditar.
        sa.Column("lote_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("descripcion", sa.Text(), nullable=True),
        sa.Column("operador_id", sa.String(80), nullable=False),
        sa.Column("anulado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anulado_por", sa.String(80), nullable=True),
        sa.Column("motivo_anulacion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_ajustes_caja_monto_positive"),
        sa.CheckConstraint(
            "cotizacion_usd IS NULL OR cotizacion_usd > 0",
            name="ck_ajustes_caja_cotizacion_positive",
        ),
        sa.ForeignKeyConstraint(["lote_id"], ["movimientos_efectivo.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_ajustes_caja_fecha",  "ajustes_caja", ["fecha"])
    op.create_index("ix_ajustes_caja_moneda", "ajustes_caja", ["moneda"])

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_ajustes_caja_updated_at
            BEFORE UPDATE ON ajustes_caja
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_ajustes_caja_updated_at ON ajustes_caja"))
    op.drop_index("ix_ajustes_caja_moneda", table_name="ajustes_caja")
    op.drop_index("ix_ajustes_caja_fecha",  table_name="ajustes_caja")
    op.drop_table("ajustes_caja")

    op.drop_column("movimientos_efectivo", "es_ajuste")

    bind = op.get_bind()
    ajuste_caja_motivo.drop(bind, checkfirst=True)

    # Nota: no se quita 'AJUSTE_CAJA' del enum caja_categoria: PostgreSQL no
    # soporta DROP VALUE. Queda como valor no usado si se baja.
