"""Registro de bugs: cada error con su numeral

Hasta acá un error se contaba solo. El del bot avisaba por Telegram con el tipo
y el archivo, pero sin nombre y sin memoria: el mismo problema tres días
seguidos eran tres avisos sueltos, imposibles de relacionar. Y el del panel
directamente no avisaba nada — moría en los logs de Railway y se enteraba el
operador, cuando ya no podía trabajar.

Desde acá cada error único tiene un número. El número es lo que viaja a
Telegram y lo que se busca en `docs/BUGS.md`; el traceback se queda en esta
tabla, que es de casa. La `huella` (tipo + archivo:línea + ámbito) es lo que
junta el mismo error mil veces en una sola fila con un contador, en lugar de
mil filas iguales.

Revision ID: 0027
Revises: 0026
Create Date: 2026-08-25
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "0027"
down_revision: Union[str, None] = "0026"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bugs",
        # El numeral: entero autoincremental, para poder decir "el bug 47".
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("huella", sa.String(64), nullable=False),
        sa.Column("origen", sa.String(20), nullable=False),
        sa.Column("titulo", sa.String(200), nullable=False),
        sa.Column("tipo", sa.String(120), nullable=False),
        sa.Column("ubicacion", sa.String(200), nullable=False),
        sa.Column("ambito", sa.String(200), nullable=False, server_default=""),
        sa.Column("detalle", sa.Text(), nullable=False, server_default=""),
        sa.Column("contexto", JSONB, nullable=True),
        sa.Column("ocurrencias", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "primera_vez", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "ultima_vez", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("estado", sa.String(20), nullable=False, server_default="ABIERTO"),
        sa.Column("notas", sa.Text(), nullable=True),
        sa.Column("sesion_test", sa.String(60), nullable=True),
        sa.Column("ultimo_aviso_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("avisos_enviados", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        # La única que importa de verdad: es la que hace que el mismo error
        # repetido sume una ocurrencia en vez de abrir un bug nuevo. Sin esto,
        # una falla sistemática abriría miles de filas y ningún número serviría.
        sa.UniqueConstraint("huella", name="uq_bugs_huella"),
        sa.CheckConstraint("estado IN ('ABIERTO', 'EN_CURSO', 'CERRADO')", name="ck_bugs_estado"),
        sa.CheckConstraint("ocurrencias > 0", name="ck_bugs_ocurrencias_positive"),
    )
    op.create_index("ix_bugs_huella", "bugs", ["huella"])
    op.create_index("ix_bugs_origen", "bugs", ["origen"])
    op.create_index("ix_bugs_estado", "bugs", ["estado"])
    # El listado por defecto es "lo último que pasó", y el documento se arma
    # recorriendo abiertos por fecha.
    op.create_index("ix_bugs_ultima_vez", "bugs", ["ultima_vez"])


def downgrade() -> None:
    op.drop_index("ix_bugs_ultima_vez", table_name="bugs")
    op.drop_index("ix_bugs_estado", table_name="bugs")
    op.drop_index("ix_bugs_origen", table_name="bugs")
    op.drop_index("ix_bugs_huella", table_name="bugs")
    op.drop_table("bugs")
