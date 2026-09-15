"""Registro de operaciones: lo que pasó y no deja rastro en ningún lado

Movimientos es el diario del negocio: **toda operación tiene que dejar renglón,
mueva plata o no** _(decisión del dueño, 2026-09-14)_. Hasta acá el feed se
armaba derivando: el libro de caja, los cheques, los fiados, las compensaciones,
los pasivos. Todo lo que dejaba una fila en alguna tabla se podía mostrar.

Quedaban afuera tres cosas que **no dejan fila en ninguna parte**:

  - **El cobro con cheque.** El cliente paga su cuenta, una cuota o un fiado con
    papeles: bajan saldos, el cheque entra a cartera y de la operación en sí no
    queda nada. En Movimientos se veía entrar el papel y no que había saldado
    una deuda.
  - **La anulación.** Deshacer borra las líneas de caja y marca la fila como
    anulada; el renglón del día **desaparece** y nada cuenta que se deshizo.
  - **La corrección.** Editar un monto o una cotización reescribe la línea del
    libro. El día muestra el número nuevo y no queda nada del viejo — no hay
    historial de ediciones en ninguna tabla.

`eventos` es ese registro. Una fila por operación que hay que contar y no se
puede derivar, con el texto ya armado para leer en Movimientos. No reemplaza
nada de lo que se deriva: **un hecho que ya se ve por el libro de caja o por su
propia tabla no escribe acá**, o se mostraría dos veces.

Las filas **no se anulan ni se borran**: son el diario. Si la operación que
generó un evento se deshace, lo que corresponde es otro evento contando la
anulación, no hacer desaparecer el primero.

Revision ID: 0033
Revises: 0032
Create Date: 2026-09-14
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0033"
down_revision: Union[str, None] = "0032"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eventos",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        # Fecha operativa (local ART): el día al que pertenece el renglón.
        sa.Column("fecha", sa.Date(), nullable=False, index=True),
        sa.Column("categoria", sa.String(40), nullable=False),
        sa.Column("grupo", sa.String(30), nullable=False),
        sa.Column("descripcion", sa.Text(), nullable=False),
        # Opcionales: una corrección de cotización no tiene monto propio.
        sa.Column("monto", sa.Numeric(18, 2), nullable=True),
        # `postgresql.ENUM(create_type=False)` y no `sa.Enum`: el tipo `moneda` ya
        # existe desde la 0001 y el genérico intenta crearlo igual — la migración
        # muere con "ya existe un tipo moneda" a mitad de camino.
        sa.Column(
            "moneda",
            postgresql.ENUM("ARS", "USD", name="moneda", create_type=False),
            nullable=True,
        ),
        sa.Column("referencia_tipo", sa.String(40), nullable=True),
        sa.Column("referencia_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("operador", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("eventos")
