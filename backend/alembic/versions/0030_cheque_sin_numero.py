"""El e-cheq que llega sin número

El cliente reenvía el comprobante del home banking, y hay dos formatos que
significan cosas distintas:

  - **Endoso** (el papel pasa a ser tuyo): trae el número del e-cheq.
  - **Emisión** (alguien lo crea a favor de otro): NO lo trae.

El operador no elige cuál le mandan, así que el caso "sin número" no es una
excepción rara: es la mitad de los comprobantes. Hasta acá `nro_cheque` era
obligatorio y esa carga no tenía manera de entrar.

Desde acá el número es opcional y sigue el mismo régimen que el banco (§Identidad,
decisión del dueño 2026-08-31): **se avisa y se carga igual**, con el resto de los
datos —monto, fecha de pago, tipo—, que es lo que mueve la plata. El operador lo
completa después con EDITAR cuando lo tenga.

**Lo que se pierde sin número, y hay que decirlo:** el cheque no se puede nombrar
por WhatsApp. `resolve_cheque` resuelve por número, así que "vendí el 13332" no
tiene con qué encontrarlo: esos cheques se operan desde el panel, o se les
completa el número antes.

**Por qué el índice único NO usa COALESCE en `nro_cheque`** (sí lo usa en `banco`):
dos e-cheq sin número son cheques **distintos**, no el mismo dos veces. Con un
COALESCE, el segundo sin número chocaría contra el primero y no se podría cargar.
Con NULL crudo cada uno entra por su lado, que es lo correcto: cuando no sabemos
el número, no tenemos con qué afirmar que son la misma lámina. El precio es que la
protección contra el duplicado no aplica ahí —igual que le pasaba al banco antes
de la 0028—, y por eso el bot avisa.

Revision ID: 0030
Revises: 0029
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0030"
down_revision: Union[str, None] = "0029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("cheques", "nro_cheque", existing_type=sa.String(64), nullable=True)


def downgrade() -> None:
    # Volver atrás exige que no haya ningún cheque sin número: la columna no puede
    # pasar a NOT NULL con filas en NULL. Postgres falla ahí con un error opaco,
    # así que se avisa antes qué pasa y cuál es la salida.
    op.execute(
        """
        DO $$
        DECLARE sin_numero int;
        BEGIN
            SELECT count(*) INTO sin_numero FROM cheques WHERE nro_cheque IS NULL;
            IF sin_numero > 0 THEN
                RAISE EXCEPTION
                    'No se puede volver a 0029: hay % cheque(s) sin número (e-cheq '
                    'cargados desde un comprobante de emisión). Completales el número '
                    'o anulalos antes de bajar la migración.', sin_numero;
            END IF;
        END $$;
        """
    )
    op.alter_column("cheques", "nro_cheque", existing_type=sa.String(64), nullable=False)
