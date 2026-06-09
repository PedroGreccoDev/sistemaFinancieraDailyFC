"""fix pasivo_estado enum values to uppercase

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-08

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Rename enum values to uppercase to match SQLAlchemy name-based serialization
    conn.execute(sa.text("ALTER TYPE pasivo_estado RENAME VALUE 'pendiente' TO 'PENDIENTE'"))
    conn.execute(sa.text("ALTER TYPE pasivo_estado RENAME VALUE 'cancelada' TO 'CANCELADA'"))
    # Update server default to match new values
    conn.execute(sa.text("ALTER TABLE pasivos ALTER COLUMN estado SET DEFAULT 'PENDIENTE'"))


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE pasivos ALTER COLUMN estado SET DEFAULT 'pendiente'"))
    conn.execute(sa.text("ALTER TYPE pasivo_estado RENAME VALUE 'PENDIENTE' TO 'pendiente'"))
    conn.execute(sa.text("ALTER TYPE pasivo_estado RENAME VALUE 'CANCELADA' TO 'cancelada'"))
