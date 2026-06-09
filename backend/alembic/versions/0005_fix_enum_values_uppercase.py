"""fix all enum values to uppercase to match SQLAlchemy name serialization

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-09

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # movimiento_efectivo_tipo
    conn.execute(sa.text("ALTER TYPE movimiento_efectivo_tipo RENAME VALUE 'compra' TO 'COMPRA'"))
    conn.execute(sa.text("ALTER TYPE movimiento_efectivo_tipo RENAME VALUE 'venta' TO 'VENTA'"))

    # prestamo_estado
    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'activo' TO 'ACTIVO'"))
    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'cancelado' TO 'CANCELADO'"))
    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'en_mora' TO 'EN_MORA'"))

    # cuota_estado
    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'pendiente' TO 'PENDIENTE'"))
    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'cobrada' TO 'COBRADA'"))
    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'en_mora' TO 'EN_MORA'"))

    # frecuencia_cuotas
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'diaria' TO 'DIARIA'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'semanal' TO 'SEMANAL'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'quincenal' TO 'QUINCENAL'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'mensual' TO 'MENSUAL'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'anual' TO 'ANUAL'"))

    # Update server defaults where applicable
    conn.execute(sa.text("ALTER TABLE prestamos ALTER COLUMN estado SET DEFAULT 'ACTIVO'"))
    conn.execute(sa.text("ALTER TABLE cuotas ALTER COLUMN estado SET DEFAULT 'PENDIENTE'"))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(sa.text("ALTER TABLE prestamos ALTER COLUMN estado SET DEFAULT 'activo'"))
    conn.execute(sa.text("ALTER TABLE cuotas ALTER COLUMN estado SET DEFAULT 'pendiente'"))

    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'ANUAL' TO 'anual'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'MENSUAL' TO 'mensual'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'QUINCENAL' TO 'quincenal'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'SEMANAL' TO 'semanal'"))
    conn.execute(sa.text("ALTER TYPE frecuencia_cuotas RENAME VALUE 'DIARIA' TO 'diaria'"))

    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'EN_MORA' TO 'en_mora'"))
    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'COBRADA' TO 'cobrada'"))
    conn.execute(sa.text("ALTER TYPE cuota_estado RENAME VALUE 'PENDIENTE' TO 'pendiente'"))

    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'EN_MORA' TO 'en_mora'"))
    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'CANCELADO' TO 'cancelado'"))
    conn.execute(sa.text("ALTER TYPE prestamo_estado RENAME VALUE 'ACTIVO' TO 'activo'"))

    conn.execute(sa.text("ALTER TYPE movimiento_efectivo_tipo RENAME VALUE 'VENTA' TO 'venta'"))
    conn.execute(sa.text("ALTER TYPE movimiento_efectivo_tipo RENAME VALUE 'COMPRA' TO 'compra'"))
