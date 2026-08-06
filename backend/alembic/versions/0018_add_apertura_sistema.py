"""Apertura del sistema: cartera preexistente + saldo inicial de caja

Régimen definido 2026-08-06. Al poner el sistema en marcha, el negocio ya venía
funcionando: había efectivo en el cajón y cheques en cartera comprados tiempo
atrás. Ambos son **saldos de apertura**, no operaciones del día.

El problema que resuelve: cada alta de cheque asienta un EGRESO `COMPRA_CHEQUE`,
porque asume que se está comprando en ese momento. Al cargar la cartera vieja eso
inventa egresos que nunca ocurrieron — y como el efectivo inicial YA tiene
descontados esos cheques, la plata se restaría dos veces.

Solución: una fecha de corte. Todo cheque cargado hasta esa fecha es inventario de
apertura y no toca la caja; a partir de ahí la operación es normal. Es automático
—no depende de que el operador tilde nada— porque el olvido es justamente donde se
cometen los errores.

Revision ID: 0018
Revises: 0017
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0018"
down_revision: Union[str, None] = "0017"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Marca de inventario de apertura. Se resuelve en el alta contra la fecha de
    # corte y queda persistida: así el cheque conserva su naturaleza aunque la
    # fecha de corte se cambie después.
    op.add_column(
        "cheques",
        sa.Column("es_carga_inicial", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Configuración singleton: una sola fila, garantizada por un CHECK sobre una
    # columna fija. Evita la clase de bug donde aparecen dos configuraciones y
    # nadie sabe cuál vale.
    op.create_table(
        "configuracion_apertura",
        sa.Column("id", sa.Integer(), nullable=False),
        # Hasta esta fecha (inclusive), los cheques cargados son cartera preexistente
        # y no asientan egreso. NULL = todavía no se definió el corte.
        sa.Column("fecha_corte_carga_inicial", sa.Date(), nullable=True),
        # Efectivo en mano al arrancar, por moneda.
        sa.Column("saldo_inicial_ars", sa.Numeric(18, 2), nullable=True),
        sa.Column("saldo_inicial_usd", sa.Numeric(18, 2), nullable=True),
        # Día al que corresponde ese efectivo (no el día en que se tipeó).
        sa.Column("fecha_saldo_inicial", sa.Date(), nullable=True),
        # Auditoría de quién fijó la apertura: es por única vez y define la caja.
        sa.Column("definido_por", sa.String(80), nullable=True),
        sa.Column("definido_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_configuracion_apertura_singleton"),
        sa.CheckConstraint(
            "saldo_inicial_ars IS NULL OR saldo_inicial_ars >= 0",
            name="ck_configuracion_apertura_ars_no_negativo",
        ),
        sa.CheckConstraint(
            "saldo_inicial_usd IS NULL OR saldo_inicial_usd >= 0",
            name="ck_configuracion_apertura_usd_no_negativo",
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_configuracion_apertura_updated_at
            BEFORE UPDATE ON configuracion_apertura
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )

    # La fila nace vacía: el sistema arranca sin apertura definida y el panel
    # muestra el estado "pendiente" hasta que el dueño la fije.
    op.execute(sa.text("INSERT INTO configuracion_apertura (id) VALUES (1)"))

    # Nueva categoría de caja para el saldo de apertura. No es un ingreso del día:
    # el reporte la trata aparte para no inflar el neto de la jornada en que se carga.
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'SALDO_INICIAL'")


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_configuracion_apertura_updated_at ON configuracion_apertura"))
    op.drop_table("configuracion_apertura")
    op.drop_column("cheques", "es_carga_inicial")
    # PostgreSQL no soporta DROP VALUE en un enum: 'SALDO_INICIAL' queda como
    # valor no usado si se baja esta migración.
