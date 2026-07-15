"""Add monto_pagado a cuotas (pago parcial de importe libre en préstamos)

Habilita cancelar un préstamo pagando cualquier importe (parcial o total): el
pago se imputa a las cuotas más viejas primero, llenando `monto_pagado` de cada
una; la cuota queda COBRADA solo cuando `monto_pagado == monto`. El saldo de una
cuota pasa a ser `monto - monto_pagado`.

Backfill: las cuotas ya COBRADA se dan por pagas en su totalidad
(`monto_pagado = monto`); las PENDIENTE/EN_MORA arrancan en 0.

Revision ID: 0015
Revises: 0014
Create Date: 2026-07-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0015"
down_revision: Union[str, None] = "0014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nace con default server-side 0 para poblar las filas existentes sin backfill
    # manual; luego se quita el default para que el ORM sea la única fuente del valor.
    op.add_column(
        "cuotas",
        sa.Column(
            "monto_pagado",
            sa.Numeric(18, 2),
            nullable=False,
            server_default="0",
        ),
    )
    # Las cuotas ya cobradas están pagas por completo.
    op.execute("UPDATE cuotas SET monto_pagado = monto WHERE estado = 'COBRADA'")
    op.alter_column("cuotas", "monto_pagado", server_default=None)
    op.create_check_constraint(
        "ck_cuotas_monto_pagado_range",
        "cuotas",
        "monto_pagado >= 0 AND monto_pagado <= monto",
    )


def downgrade() -> None:
    op.drop_constraint("ck_cuotas_monto_pagado_range", "cuotas", type_="check")
    op.drop_column("cuotas", "monto_pagado")
