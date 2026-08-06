"""Add columnas de anulación a las entidades de negocio

Régimen definido 2026-08-06: "Eliminar" en el panel NO borra la fila, la **anula**.
El registro conserva su historia (para auditar por qué la caja dio distinto) pero
sale de los listados y se revierten sus líneas de caja.

La anulación es **ortogonal al estado** de cada entidad: un cheque anulado conserva
su `estado` histórico (EN_CARTERA/VENDIDO/…) y no se agrega un valor ANULADO al enum
`cheque_estado`, que rompería la máquina de estados y los reportes. La marca vive en
`anulado_at`; los listados filtran `anulado_at IS NULL`.

Revision ID: 0017
Revises: 0016
Create Date: 2026-08-06
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0017"
down_revision: Union[str, None] = "0016"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Entidades que se pueden anular desde el panel. `fiados` entra porque la anulación
# de un cheque FIADO tiene que arrastrar el fiado que originó.
_TABLAS: tuple[str, ...] = (
    "cheques",
    "prestamos",
    "movimientos_efectivo",
    "fiados",
    "deudas_simples",
    "pasivos",
    "gastos_operativos",
)


def upgrade() -> None:
    # Sin índice sobre `anulado_at`: las anulaciones son excepcionales, así que
    # casi todas las filas quedan en NULL y el predicado `anulado_at IS NULL` no
    # es selectivo — un índice ahí no lo usaría el planner y solo encarecería las
    # escrituras. Los listados siguen resolviéndose por sus índices actuales.
    for tabla in _TABLAS:
        op.add_column(tabla, sa.Column("anulado_at", sa.DateTime(timezone=True), nullable=True))
        op.add_column(tabla, sa.Column("anulado_por", sa.String(80), nullable=True))
        op.add_column(tabla, sa.Column("motivo_anulacion", sa.Text(), nullable=True))

    # La unicidad (banco, nro_cheque) tiene que ignorar los cheques anulados: el
    # caso normal es cargar mal un cheque, anularlo y volver a cargarlo con el
    # mismo número. Con la constraint plana el recargue chocaba contra la fila
    # anulada. Un índice único PARCIAL mantiene la garantía entre los vivos y
    # deja libre el número una vez anulado.
    # DROP ... IF EXISTS (mismo patrón que 0010): el entrypoint corre `alembic
    # upgrade head` con `set -e`, así que un nombre de constraint que no matchee
    # tumbaría el arranque del contenedor. Con IF EXISTS la migración es
    # idempotente y no puede dejar la app caída.
    op.execute("ALTER TABLE cheques DROP CONSTRAINT IF EXISTS uq_cheques_banco_nro")
    op.execute("DROP INDEX IF EXISTS uq_cheques_banco_nro")
    op.create_index(
        "uq_cheques_banco_nro_vivos",
        "cheques",
        ["banco", "nro_cheque"],
        unique=True,
        postgresql_where=sa.text("anulado_at IS NULL"),
    )

    # Un cheque solo puede originar un fiado, con la misma salvedad: si el fiado
    # se anuló, el cheque tiene que poder volver a fiarse.
    op.execute("ALTER TABLE fiados DROP CONSTRAINT IF EXISTS uq_fiados_cheque_id")
    op.execute("DROP INDEX IF EXISTS uq_fiados_cheque_id")
    op.create_index(
        "uq_fiados_cheque_vivos",
        "fiados",
        ["cheque_id"],
        unique=True,
        postgresql_where=sa.text("anulado_at IS NULL"),
    )


def downgrade() -> None:
    # Al volver atrás, las filas anuladas pasan a contar para la unicidad: si hay
    # un número repetido entre una viva y una anulada, el constraint no se puede
    # recrear. Se avisa explícito en vez de fallar con un error opaco de Postgres.
    op.execute("DROP INDEX IF EXISTS uq_fiados_cheque_vivos")
    op.create_unique_constraint("uq_fiados_cheque_id", "fiados", ["cheque_id"])

    op.execute("DROP INDEX IF EXISTS uq_cheques_banco_nro_vivos")
    op.create_unique_constraint("uq_cheques_banco_nro", "cheques", ["banco", "nro_cheque"])

    for tabla in _TABLAS:
        op.drop_column(tabla, "motivo_anulacion")
        op.drop_column(tabla, "anulado_por")
        op.drop_column(tabla, "anulado_at")
