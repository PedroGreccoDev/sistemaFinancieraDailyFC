"""A qué acreedor se le entregó el cheque

Un cheque puede salir de cartera de cinco maneras y hasta acá el sistema solo
sabía **a quién** se le fue en dos: vendido o fiado a un cliente
(`cliente_destino_id`). La tercera —entregárselo a un acreedor para pagarle una
deuda del negocio (§5)— dejaba el cheque en `VENDIDO` y nada más: el nombre del
que se lo llevó no quedaba en ninguna columna.

Mientras esa operación solo bajaba un saldo alcanzaba con eso. Desde que las
salidas de cartera se ven en **Movimientos** (§Historial unificado), no: la línea
tiene que decir quién se llevó el papel, que es todo lo que queda de una
operación que no mueve un peso.

`acreedor_destino` es **texto**, igual que `pasivos.acreedor` y por la misma
razón: se le puede deber a alguien que no es cliente del sistema, así que no hay
FK que ponerle. No se hace backfill —el dato no existe en ningún lado— y las
entregas anteriores se siguen mostrando, pero sin nombre: Movimientos las
reconoce por no tener ingreso de venta en el libro de caja, no por esta columna.

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cheques",
        sa.Column("acreedor_destino", sa.String(200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cheques", "acreedor_destino")
