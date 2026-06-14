"""Add foto (imagen del cheque) to cheques

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Foto del cheque cargado por WhatsApp (OCR). Se guarda el binario tal cual
    # se recibió de WAHA. Nullable: los cheques cargados a mano no tienen foto.
    op.add_column("cheques", sa.Column("foto", sa.LargeBinary(), nullable=True))
    op.add_column("cheques", sa.Column("foto_mime", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("cheques", "foto_mime")
    op.drop_column("cheques", "foto")
