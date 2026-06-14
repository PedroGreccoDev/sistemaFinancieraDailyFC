"""Cheque: PK subrogada (id) + banco, e identidad (banco, nro_cheque)

El número de cheque NO es único globalmente (solo dentro de un banco). Hasta acá
`nro_cheque` era la PK de `cheques`, así que dos cheques de bancos distintos con el
mismo número chocaban ("Ya existe un cheque con ese numero") aunque fueran cheques
distintos. Esta migración:

  - Agrega `id` (UUID) como PK subrogada de `cheques` y una columna `banco`.
  - Reemplaza la unicidad por (banco, nro_cheque).
  - Reapunta el FK de `fiados` (cheque_nro → cheque_id).
  - Elimina el FK/columna vestigial `prestamos.cheque_origen_nro` (los préstamos no
    tienen cheque asociado; el campo siempre estuvo en NULL).

Sistema en desarrollo: los datos son descartables, así que se vacía `fiados` (única
tabla con FK obligatorio al cheque) en vez de migrar sus vínculos uno a uno.

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Datos descartables: vaciamos las dependencias del cheque para no arrastrar el
    # esquema viejo. (fiados tiene FK NOT NULL al cheque; prestamos lo pierde abajo.)
    op.execute("TRUNCATE TABLE fiados")

    # ── cheques: PK subrogada `id` + columna `banco`, unicidad (banco, nro_cheque) ──
    op.add_column(
        "cheques",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True),
            nullable=False, server_default=sa.text("gen_random_uuid()"),
        ),
    )
    op.add_column("cheques", sa.Column("banco", sa.String(120), nullable=True))

    # fiados y prestamos referencian cheques.nro_cheque: hay que soltar esos FK antes
    # de cambiar la PK de cheques.
    op.execute("ALTER TABLE fiados DROP CONSTRAINT IF EXISTS fiados_cheque_nro_fkey")
    op.execute("ALTER TABLE fiados DROP CONSTRAINT IF EXISTS uq_fiados_cheque_nro")
    op.execute("DROP INDEX IF EXISTS ix_fiados_cheque_nro")
    op.drop_column("fiados", "cheque_nro")

    op.execute("ALTER TABLE prestamos DROP CONSTRAINT IF EXISTS prestamos_cheque_origen_nro_fkey")
    op.drop_column("prestamos", "cheque_origen_nro")

    op.execute("ALTER TABLE cheques DROP CONSTRAINT IF EXISTS cheques_pkey")
    op.create_primary_key("cheques_pkey", "cheques", ["id"])
    op.alter_column("cheques", "id", server_default=None)
    op.create_index("ix_cheques_nro_cheque", "cheques", ["nro_cheque"])
    op.create_unique_constraint("uq_cheques_banco_nro", "cheques", ["banco", "nro_cheque"])

    # ── fiados: nuevo FK sobre cheque_id ─────────────────────────────────────
    op.add_column(
        "fiados", sa.Column("cheque_id", postgresql.UUID(as_uuid=True), nullable=False)
    )
    op.create_foreign_key(
        "fiados_cheque_id_fkey", "fiados", "cheques",
        ["cheque_id"], ["id"], ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_fiados_cheque_id", "fiados", ["cheque_id"])
    op.create_index("ix_fiados_cheque_id", "fiados", ["cheque_id"])


def downgrade() -> None:
    op.execute("TRUNCATE TABLE fiados")

    # ── fiados: volver a cheque_nro ──────────────────────────────────────────
    op.execute("ALTER TABLE fiados DROP CONSTRAINT IF EXISTS fiados_cheque_id_fkey")
    op.execute("ALTER TABLE fiados DROP CONSTRAINT IF EXISTS uq_fiados_cheque_id")
    op.execute("DROP INDEX IF EXISTS ix_fiados_cheque_id")
    op.drop_column("fiados", "cheque_id")

    # ── cheques: restaurar PK sobre nro_cheque ───────────────────────────────
    op.execute("ALTER TABLE cheques DROP CONSTRAINT IF EXISTS uq_cheques_banco_nro")
    op.execute("DROP INDEX IF EXISTS ix_cheques_nro_cheque")
    op.execute("ALTER TABLE cheques DROP CONSTRAINT IF EXISTS cheques_pkey")
    op.create_primary_key("cheques_pkey", "cheques", ["nro_cheque"])

    # ── prestamos: restaurar cheque_origen_nro ───────────────────────────────
    op.add_column("prestamos", sa.Column("cheque_origen_nro", sa.String(64), nullable=True))
    op.create_foreign_key(
        "prestamos_cheque_origen_nro_fkey", "prestamos", "cheques",
        ["cheque_origen_nro"], ["nro_cheque"], ondelete="SET NULL",
    )

    # ── fiados: FK clásico + soltar columnas nuevas de cheques ───────────────
    op.add_column("fiados", sa.Column("cheque_nro", sa.String(64), nullable=False))
    op.create_foreign_key(
        "fiados_cheque_nro_fkey", "fiados", "cheques",
        ["cheque_nro"], ["nro_cheque"], ondelete="RESTRICT",
    )
    op.create_unique_constraint("uq_fiados_cheque_nro", "fiados", ["cheque_nro"])
    op.create_index("ix_fiados_cheque_nro", "fiados", ["cheque_nro"])

    op.drop_column("cheques", "banco")
    op.drop_column("cheques", "id")
