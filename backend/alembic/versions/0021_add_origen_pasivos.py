"""Comprar sin abonar: el pasivo recuerda de qué compra salió

Hasta acá toda compra descontaba la caja en el acto: comprar dólares asentaba el
egreso en pesos y comprar un cheque también. Pero el negocio compra a crédito —un
lote de dólares o un cheque que se paga después—, y esa plata **no salió de la
caja**: quedó debiéndose. Cargarla como compra pagada descuenta un egreso que no
ocurrió; cargar el pasivo aparte lo descuenta dos veces.

Desde acá una compra puede quedar debida (total o parcialmente) y **genera sola**
el pasivo por lo que falta pagar. `origen_tipo`/`origen_id` son ese vínculo: sin
él, anular la compra dejaría vivo un pasivo huérfano por plata que ya no se debe,
y nadie lo notaría hasta pagarlo de nuevo.

El vínculo es genérico (tipo + id) y no una FK por tabla porque las dos compras
que lo usan —divisas y cheques— viven en tablas distintas y se comportan igual;
es el mismo criterio que `referencia_tipo`/`referencia_id` del libro de caja.

Revision ID: 0021
Revises: 0020
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0021"
down_revision: Union[str, None] = "0020"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Qué operación generó este pasivo: 'movimiento_efectivo' (compra de dólares a
    # deber) o 'cheque' (compra de cheque a deber). NULL = pasivo cargado a mano,
    # que es como se cargaron todos hasta esta migración.
    op.add_column(
        "pasivos",
        sa.Column("origen_tipo", sa.String(40), nullable=True),
    )
    op.add_column(
        "pasivos",
        sa.Column("origen_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    # Lo consulta la anulación de la compra para encontrar su pasivo.
    op.create_index(
        "ix_pasivos_origen", "pasivos", ["origen_tipo", "origen_id"]
    )

    # Cuánto se abonó realmente por la compra, en pesos. NULL = se pagó todo, que
    # es lo que valen todas las filas anteriores a esta migración y sigue siendo
    # el caso normal.
    #
    # Es un dato de la operación y no algo derivable: el egreso de caja se
    # reconstruye desde acá cada vez que se edita la compra (`resync_caja_cheque`,
    # `_resync_caja_compra`). Sin guardarlo, resincronizar una compra a deber le
    # inventaría el egreso completo que nunca ocurrió. Tampoco sirve deducirlo del
    # saldo del pasivo: ese saldo baja con cada pago, y lo que se abonó el día de
    # la compra no cambia nunca.
    op.add_column(
        "cheques",
        sa.Column("monto_abonado", sa.Numeric(18, 2), nullable=True),
    )
    op.add_column(
        "movimientos_efectivo",
        sa.Column("monto_abonado", sa.Numeric(18, 2), nullable=True),
    )
    op.create_check_constraint(
        "ck_cheques_monto_abonado_no_negativo", "cheques",
        "monto_abonado IS NULL OR monto_abonado >= 0",
    )
    op.create_check_constraint(
        "ck_movimientos_efectivo_monto_abonado_no_negativo", "movimientos_efectivo",
        "monto_abonado IS NULL OR monto_abonado >= 0",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_movimientos_efectivo_monto_abonado_no_negativo",
        "movimientos_efectivo", type_="check",
    )
    op.drop_constraint(
        "ck_cheques_monto_abonado_no_negativo", "cheques", type_="check"
    )
    op.drop_column("movimientos_efectivo", "monto_abonado")
    op.drop_column("cheques", "monto_abonado")

    op.drop_index("ix_pasivos_origen", table_name="pasivos")
    op.drop_column("pasivos", "origen_id")
    op.drop_column("pasivos", "origen_tipo")
