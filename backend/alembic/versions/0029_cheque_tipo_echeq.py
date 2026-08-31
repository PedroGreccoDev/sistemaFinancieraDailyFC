"""E-cheq: el cheque que no tiene lámina

Hasta acá el sistema solo conocía cheques de papel: el bot los cargaba por foto y
el contrato del OCR describía una lámina impresa. El e-cheq no existía en ningún
lado —ni en el modelo, ni en el prompt, ni en el panel—, y cuando el operador
dictaba uno el modelo no tenía número que poner: quedaron tres cheques cuyo
`nro_cheque` es, literalmente, la palabra "echeq".

Esta migración le da un tipo al cheque. Es una **etiqueta, no un compartimento**
(decisión del dueño): las dos clases viven en la misma cartera y suman al mismo
total, porque es la misma plata. Lo que cambia es cómo entra al sistema —el de
papel por foto del cheque, el electrónico por el comprobante de transferencia que
reenvía el cliente— y que un e-cheq no tiene lámina que presentar.

`PAPEL` es el default y el `server_default`: es lo que era todo hasta acá, así que
las 195 filas existentes quedan bien clasificadas sin tocarlas y ninguna carga
vieja cambia de significado.

Revision ID: 0029
Revises: 0028
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0029"
down_revision: Union[str, None] = "0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # El tipo enum se crea explícito (checkfirst) y la columna lo referencia con
    # create_type=False: mismo patrón que `cheque_estado`, para que el enum no se
    # intente crear dos veces si la migración se reaplica.
    cheque_tipo = sa.Enum("PAPEL", "ELECTRONICO", name="cheque_tipo")
    cheque_tipo.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "cheques",
        sa.Column(
            "tipo",
            sa.Enum("PAPEL", "ELECTRONICO", name="cheque_tipo", create_type=False),
            nullable=False,
            # Todo lo cargado hasta acá era papel: el default deja las filas
            # existentes bien clasificadas sin un UPDATE aparte.
            server_default="PAPEL",
        ),
    )


def downgrade() -> None:
    op.drop_column("cheques", "tipo")
    sa.Enum(name="cheque_tipo").drop(op.get_bind(), checkfirst=True)
