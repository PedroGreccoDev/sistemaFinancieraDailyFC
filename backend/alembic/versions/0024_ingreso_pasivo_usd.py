"""Préstamo recibido en dólares: además de la caja USD, su lote de stock

La 0023 hizo que un préstamo recibido sume a la caja de su moneda. Para los pesos
alcanza, pero **la caja USD y el stock vendible son cosas distintas** (§4): la venta
consume lotes `MovimientoEfectivo` con su costo real, así que unos dólares que solo
figuran en la caja no se pueden vender —la venta falla con "no hay stock"—.

Es el mismo agujero que ya se tapó dos veces: los dólares de apertura (0019) y los
ajustes que suman USD (0020). Y se resuelve igual: el operador declara a cuánto valúa
esos dólares (`cotizacion_ingreso_usd`) y el alta crea su lote (`es_ajuste=True`, que
es la marca de "stock que entró sin una compra detrás"). El costo del lote es contra
lo que se calcula la ganancia el día que se vendan.

`lote_id` guarda cuál es, para poder borrarlo si la carga se corrige o se anula.

Revision ID: 0024
Revises: 0023
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0024"
down_revision: Union[str, None] = "0023"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "pasivos", sa.Column("cotizacion_ingreso_usd", sa.Numeric(18, 6), nullable=True)
    )
    op.add_column(
        "pasivos", sa.Column("lote_id", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.create_foreign_key(
        "fk_pasivos_lote_id",
        "pasivos",
        "movimientos_efectivo",
        ["lote_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_pasivos_cotizacion_ingreso_positive",
        "pasivos",
        "cotizacion_ingreso_usd IS NULL OR cotizacion_ingreso_usd > 0",
    )
    # Dólares prestados sin costo declarado no pueden entrar al stock: mejor frenar
    # en la carga que descubrirlo el día que se los quiera vender.
    op.create_check_constraint(
        "ck_pasivos_ingreso_usd_cotizacion",
        "pasivos",
        "NOT (ingreso_caja AND moneda = 'USD') OR cotizacion_ingreso_usd IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_pasivos_ingreso_usd_cotizacion", "pasivos", type_="check")
    op.drop_constraint("ck_pasivos_cotizacion_ingreso_positive", "pasivos", type_="check")
    op.drop_constraint("fk_pasivos_lote_id", "pasivos", type_="foreignkey")
    op.drop_column("pasivos", "lote_id")
    op.drop_column("pasivos", "cotizacion_ingreso_usd")
