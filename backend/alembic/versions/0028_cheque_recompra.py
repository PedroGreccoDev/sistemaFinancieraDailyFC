"""Recompra: un cheque puede volver a entrar al negocio las veces que haga falta

Un cheque que el negocio vendió sigue girando en plaza, y por el mismo circuito
puede volver a ofrecérsele. Recomprarlo es una **compra nueva y real**, con su
precio, su salida de caja y su ganancia propios: no es revertir la venta anterior
—esa ocurrió— ni un duplicado a bloquear.

Hasta acá no se podía. `uq_cheques_banco_nro_vivos` (migración 0017) exigía un
solo cheque **vivo** por (banco, nro_cheque), y el vendido sigue vivo: la segunda
compra chocaba con "Ya existe el cheque Nº …, estado VENDIDO". Los dos caminos
que quedaban falseaban la historia —revertir borraba la venta, anular la hacía
desaparecer—.

Desde acá cada pasada del cheque por el negocio es **una fila propia**, y la
unicidad se corre de "un cheque vivo" a **"un cheque EN CARTERA"**:

  - Sigue frenando el duplicado real: no se puede cargar dos veces el cheque que
    se tiene en la mano, que es contra lo que la constraint protegía.
  - Deja recomprar cuando la pasada anterior ya cerró (VENDIDO/FIADO/COBRADO/
    RECHAZADO), sin tope de vueltas.
  - Las pasadas se relacionan solas por (banco, nro_cheque): no hace falta una
    columna de vínculo que después haya que mantener sincronizada.

**Y de paso tapa un agujero anterior a todo esto.** La unicidad era sobre `banco`
a secas, y en Postgres NULL ≠ NULL: cuando el banco no se detectaba, el índice no
aplicaba en absoluto y el mismo cheque podía cargarse dos, cinco o diez veces en
silencio (pasó: tres cheques 'echeq' de $3.000.000 cargados con tres minutos de
diferencia el 28/08/26). El índice pasa a construirse sobre COALESCE(banco, ''),
así que "sin banco" es un valor más y también protege. Si fueran dos láminas de
bancos distintos ambas cargadas sin banco, la segunda choca —y la salida es la
que el operador debía tomar igual: cargarle el banco—.

Se usa COALESCE y no `NULLS NOT DISTINCT` (Postgres 15+, más elegante) para no
atarse a la versión del servidor.

Revision ID: 0028
Revises: 0027
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# El índice es de EXPRESIÓN (COALESCE) y PARCIAL (solo los vivos en cartera), así
# que se crea con SQL plano: op.create_index() no expresa la parte de expresión.
_CREATE_INDEX = """
CREATE UNIQUE INDEX uq_cheques_banco_nro_en_cartera
    ON cheques (COALESCE(banco, ''), nro_cheque)
    WHERE anulado_at IS NULL AND estado = 'EN_CARTERA'
"""


def upgrade() -> None:
    # Si los datos ya violan la unicidad nueva, Postgres corta con "no se pudo
    # crear el índice único" y una sola llave de ejemplo. Esto corre en el
    # arranque del contenedor (`alembic upgrade head` con `set -e`), así que no es
    # un deploy fallido: **el sistema no levanta**, y el log no dice qué cheques
    # son ni qué hacer con ellos. El caso no es teórico — el agujero que esta
    # misma migración tapa (el banco NULL que no bloqueaba nada) es justamente el
    # que pudo dejar copias cargadas en silencio.
    #
    # Avisa y corta; no limpia solo. Cuál de las copias sobra lo decide el
    # operador: una puede ser una lámina distinta que entró sin banco.
    op.execute(
        """
        DO $$
        DECLARE detalle text;
        BEGIN
            SELECT string_agg(
                       format('%s (banco %s) ×%s',
                              nro_cheque, COALESCE(banco, 'sin banco'), n),
                       '; ')
              INTO detalle
              FROM (
                SELECT nro_cheque, banco, count(*) AS n
                  FROM cheques
                 WHERE anulado_at IS NULL AND estado = 'EN_CARTERA'
                 GROUP BY COALESCE(banco, ''), banco, nro_cheque
                HAVING count(*) > 1
              ) c;
            IF detalle IS NOT NULL THEN
                RAISE EXCEPTION
                    'No se puede aplicar 0028: hay cheques repetidos EN CARTERA y la '
                    'unicidad nueva los prohíbe → %. Anulá las copias que sobren, o '
                    'cargales el banco si son láminas distintas, y volvé a desplegar.',
                    detalle;
            END IF;
        END $$;
        """
    )
    # DROP ... IF EXISTS (mismo patrón que 0010 y 0017): el entrypoint corre
    # `alembic upgrade head` con `set -e`, así que un nombre que no matchee
    # tumbaría el arranque del contenedor.
    op.execute("DROP INDEX IF EXISTS uq_cheques_banco_nro_vivos")
    op.execute("ALTER TABLE cheques DROP CONSTRAINT IF EXISTS uq_cheques_banco_nro_vivos")
    op.execute(_CREATE_INDEX)


def downgrade() -> None:
    # Volver atrás es estrechar la unicidad: si ya se recompró algún cheque, las
    # dos pasadas pasan a chocar y el índice viejo no se puede crear. Postgres
    # falla ahí con un error opaco ("could not create unique index"), así que se
    # avisa antes qué pasó y cuál es la salida.
    op.execute(
        """
        DO $$
        DECLARE colisiones int;
        BEGIN
            SELECT count(*) INTO colisiones FROM (
                SELECT 1 FROM cheques
                WHERE anulado_at IS NULL
                GROUP BY banco, nro_cheque
                HAVING count(*) > 1
            ) c;
            IF colisiones > 0 THEN
                RAISE EXCEPTION
                    'No se puede volver a 0027: hay % (banco, nro_cheque) con más de un '
                    'cheque vivo (cheques recomprados). La unicidad vieja los prohíbe. '
                    'Anulá las pasadas que sobren antes de bajar la migración.', colisiones;
            END IF;
        END $$;
        """
    )
    op.execute("DROP INDEX IF EXISTS uq_cheques_banco_nro_en_cartera")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_cheques_banco_nro_vivos
            ON cheques (banco, nro_cheque)
            WHERE anulado_at IS NULL
        """
    )
