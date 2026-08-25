"""Dos cajas en paralelo: el efectivo del cajón y la plata del banco

Hasta acá la caja era un solo saldo por moneda y `medio_pago` una etiqueta suelta
que solo llenaban los pagos de pasivo. Eso alcanzaba para el reporte, pero no para
cerrar el día: el dueño cuenta billetes y los compara contra un número que también
tiene adentro las transferencias, así que nunca le podía dar.

Desde acá cada moneda lleva **dos libros paralelos**. Todo movimiento cae en uno o
en el otro —nunca en los dos— y cada uno se cuadra contra su propia realidad: el
efectivo contra el cajón, la transferencia contra el resumen del banco.

Dos cambios y nada más:

1. `medio_pago` pasa a NOT NULL en `movimientos_caja`. Lo ya cargado se marca
   EFECTIVO, que es exactamente lo que el sistema venía asumiendo: ningún número
   histórico se mueve. Si algo de eso fue en realidad una transferencia, la caja
   de banco arranca corrida y se empareja una vez con un ajuste.
2. Categoría `TRASPASO_CAJA`: depositar o extraer. Es lo único que cruza de un
   libro al otro, y va siempre en **dos filas** (egreso de una caja, ingreso de
   la otra) que se cancelan solas en el neto del día — la plata no entró ni salió
   del negocio, cambió de bolsillo.

Revision ID: 0026
Revises: 0025
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0026"
down_revision: Union[str, None] = "0025"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Categoría nueva del libro de caja (idempotente). Igual que en `0023`: acá
    # solo se declara el valor; las filas que lo usan se escriben en otra
    # transacción, desde el servicio.
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'TRASPASO_CAJA'")

    # Backfill antes de imponer el NOT NULL: sin esto, cualquier fila vieja sin
    # medio —que son todas menos los pagos de pasivo— voltearía la migración.
    op.execute(
        "UPDATE movimientos_caja SET medio_pago = 'EFECTIVO' WHERE medio_pago IS NULL"
    )
    op.alter_column(
        "movimientos_caja",
        "medio_pago",
        existing_type=sa.Enum("EFECTIVO", "TRANSFERENCIA", name="medio_pago"),
        nullable=False,
    )
    # Los dos saldos se leen por separado en cada corte del reporte, siempre
    # filtrando por medio además de por moneda y fecha.
    op.create_index(
        "ix_movimientos_caja_medio_pago", "movimientos_caja", ["medio_pago"]
    )

    # Apertura: cada moneda arranca con sus dos saldos. Las columnas que ya
    # existían pasan a ser el efectivo —es lo que significaban cuando la caja era
    # una sola— y estas dos, lo depositado. Quedan nullable: una apertura vieja
    # no las tiene y el servicio las lee como cero.
    op.add_column(
        "configuracion_apertura",
        sa.Column("saldo_inicial_ars_transf", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "configuracion_apertura",
        sa.Column("saldo_inicial_usd_transf", sa.Numeric(18, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_configuracion_apertura_ars_transf_no_negativo",
        "configuracion_apertura",
        "saldo_inicial_ars_transf IS NULL OR saldo_inicial_ars_transf >= 0",
    )
    op.create_check_constraint(
        "ck_configuracion_apertura_usd_transf_no_negativo",
        "configuracion_apertura",
        "saldo_inicial_usd_transf IS NULL OR saldo_inicial_usd_transf >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_configuracion_apertura_usd_transf_no_negativo",
        "configuracion_apertura",
        type_="check",
    )
    op.drop_constraint(
        "ck_configuracion_apertura_ars_transf_no_negativo",
        "configuracion_apertura",
        type_="check",
    )
    op.drop_column("configuracion_apertura", "saldo_inicial_usd_transf")
    op.drop_column("configuracion_apertura", "saldo_inicial_ars_transf")
    op.drop_index("ix_movimientos_caja_medio_pago", table_name="movimientos_caja")
    op.alter_column(
        "movimientos_caja",
        "medio_pago",
        existing_type=sa.Enum("EFECTIVO", "TRANSFERENCIA", name="medio_pago"),
        nullable=True,
    )
    # El backfill no se deshace: no hay forma de saber cuáles filas estaban en
    # blanco antes, y dejarlas en EFECTIVO es la lectura correcta igual.

    # Nota: no se quita 'TRASPASO_CAJA' del enum caja_categoria: PostgreSQL no
    # soporta DROP VALUE. Queda como valor no usado si se baja.
