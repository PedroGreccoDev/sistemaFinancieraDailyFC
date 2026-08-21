"""Deuda con plata en mano: el pasivo que SÍ hace entrar efectivo

Hasta acá anotar una deuda del negocio nunca movía la caja, y con razón: la deuda
típica es comercial —le debo al proveedor por la mercadería— y ahí no entró un peso,
solo quedó una obligación. La caja se tocaba recién al pagarla (`PAGO_PASIVO`).

Pero hay un caso que se anotaba mal: **cuando alguien le presta plata al negocio**.
Ahí la deuda nace *y además* el efectivo entra al cajón. Anotando solo el pasivo, el
reporte del día quedaba corto contra la plata real y no había forma de cuadrarlo salvo
un ajuste manual a mano.

`ingreso_caja` marca esa diferencia en el alta y asienta un INGRESO `INGRESO_PASIVO`
por la fecha en que entró la plata (`fecha_ingreso`). Cuenta como ingreso del período,
con el mismo criterio que un aporte del dueño (§Ajustes de caja): el neto del reporte
es el flujo real de caja, y esa plata efectivamente entró.

Revision ID: 0023
Revises: 0022
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0023"
down_revision: Union[str, None] = "0022"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Categoría nueva del libro de caja (idempotente). ADD VALUE no puede usarse en
    # la misma transacción en que se agrega, pero acá solo se declara: las filas
    # nuevas la usan desde el servicio, en otra transacción.
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'INGRESO_PASIVO'")

    # Las deudas ya cargadas son todas comerciales (nunca movieron la caja), así que
    # el default false es exactamente su historia: no hay nada que backfillear.
    op.add_column(
        "pasivos",
        sa.Column("ingreso_caja", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("pasivos", sa.Column("fecha_ingreso", sa.Date(), nullable=True))

    # Si entró plata, tiene que constar cuándo: sin fecha no hay línea de caja que
    # resincronizar ni día al que imputarla.
    op.create_check_constraint(
        "ck_pasivos_ingreso_caja_fecha",
        "pasivos",
        "NOT ingreso_caja OR fecha_ingreso IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pasivos_ingreso_caja_fecha", "pasivos", type_="check")
    op.drop_column("pasivos", "fecha_ingreso")
    op.drop_column("pasivos", "ingreso_caja")

    # Nota: no se quita 'INGRESO_PASIVO' del enum caja_categoria: PostgreSQL no
    # soporta DROP VALUE. Queda como valor no usado si se baja.
