"""Préstamo a interés fijo — el capital no se amortiza, se liquida al cancelar

Hasta acá el sistema conocía una sola forma de prestar: un capital, un total a
cobrar y un cuadro de cuotas cerrado que se genera entero al alta y va bajando
hasta que no queda nada. Es la modalidad `NORMAL`, y sigue siendo la de siempre.

La segunda modalidad —la que agrega esta migración— funciona al revés:

  - **El capital no se toca en las cuotas.** Queda prestado, entero, hasta que el
    cliente lo devuelve: total (lo normal) o de a partes.
  - **Lo que se cobra cada 30 días es un interés fijo en plata**, no un
    porcentaje. El dueño lo negocia en pesos ("me paga 200 mil por mes") y lo
    puede cambiar cuando quiera, sin ninguna obligación de hacerlo.
  - **Los ciclos son de 30 días exactos** desde la fecha de cobro que se fija al
    alta. No es "mensual": 30 días es 30 días, y por eso el enum de frecuencia
    gana un valor propio (`CADA_30_DIAS`) en vez de reusar `MENSUAL`, que se
    correría con los meses de 28 y 31.
  - **Sin prorrateo.** Al entrar a un período nuevo, ese interés queda debido
    completo aunque el cliente cancele al día siguiente. Por eso la cuota del
    período se genera **el día que el período arranca**, no cuando termina.
  - **Las cuotas se devengan de a una.** No hay cuadro que pre-generar: no se
    sabe cuántos períodos va a durar el préstamo. Cada vez que se lee o se opera
    un préstamo de este tipo, el servicio crea las cuotas de los períodos que ya
    arrancaron y todavía no existían (`svc_prestamos.devengar_periodos`).
  - **La mora se acumula, no reemplaza.** El interés impago de un período queda
    `EN_MORA` y el del período siguiente se suma: se deben los dos.

Columnas nuevas en `prestamos`:

  - `tipo_prestamo` — enum `NORMAL | INTERES_FIJO`. `NORMAL` es el default y el
    `server_default`: todo lo cargado hasta acá es eso, así que las filas
    existentes quedan bien clasificadas sin un UPDATE aparte y ninguna carga
    vieja cambia de significado.
  - `monto_interes_fijo` — el interés de un período, en la moneda del préstamo.
    Editable; la edición vale para los períodos que vienen (§editar_interes_fijo).
  - `dia_cobro` — **la fecha de cobro fijada al alta**, no un día del mes. Es el
    ancla de los ciclos: el período k arranca en `dia_cobro + 30*(k-1)`. Se llama
    así porque es como lo nombra el operador ("el día de cobro es el 15").
  - `capital_pendiente` — cuánto capital falta que devuelva. Arranca en `credito`
    y solo baja con un abono explícito de capital. **Hace falta como columna**
    porque en esta modalidad el capital no vive en ninguna cuota: derivarlo de la
    caja obligaría a leer el libro entero para saber cuánto se debe.

Las tres últimas son NULL para `NORMAL` —ahí no significan nada— y obligatorias
para `INTERES_FIJO`. Un CHECK lo impone en la base, para que no dependa de que
todos los caminos de escritura se acuerden.

`cuotas` queda en **0** para `INTERES_FIJO`: no es "cero cuotas", es "no tiene
cuadro". La cantidad de períodos devengados se cuenta con las filas de `cuotas`,
que es la única fuente que no se desactualiza. Por eso el CHECK de `cuotas > 0`
se reemplaza por uno que pide lo correcto según la modalidad.

`caja_categoria` gana `DEVOLUCION_CAPITAL`: la plata que vuelve al cajón cuando
el cliente devuelve capital **no es ganancia**, y meterla en `COBRO_CUOTA` la
mezclaría con los cobros de interés en el reporte diario. El interés, en cambio,
sí entra como `COBRO_CUOTA`: es una cuota, cobrada como cualquier otra.

Revision ID: 0031
Revises: 0030
Create Date: 2026-09-10
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0031"
down_revision: Union[str, None] = "0030"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Cómo tienen que venir las columnas propias de cada modalidad. Es la regla que
# hace imposible un préstamo a interés fijo sin interés, o uno normal con un
# capital pendiente colgado de una carga a medio corregir.
_CK_COHERENCIA = """
    (
        tipo_prestamo = 'NORMAL'
        AND monto_interes_fijo IS NULL
        AND dia_cobro IS NULL
        AND capital_pendiente IS NULL
    ) OR (
        tipo_prestamo = 'INTERES_FIJO'
        AND monto_interes_fijo IS NOT NULL AND monto_interes_fijo > 0
        AND dia_cobro IS NOT NULL
        AND capital_pendiente IS NOT NULL
        AND capital_pendiente >= 0
        AND capital_pendiente <= credito
    )
"""

# `cuotas` significa cosas distintas en cada modalidad: la cantidad de cuotas del
# cuadro pactado en NORMAL, y "no hay cuadro" (0) en INTERES_FIJO.
_CK_CUOTAS = """
    (tipo_prestamo = 'NORMAL' AND cuotas > 0)
    OR (tipo_prestamo = 'INTERES_FIJO' AND cuotas = 0)
"""


def upgrade() -> None:
    bind = op.get_bind()

    # El enum se crea explícito (checkfirst) y la columna lo referencia con
    # create_type=False: mismo patrón que `cheque_tipo` (0029), para que no se
    # intente crear dos veces si la migración se reaplica.
    prestamo_tipo = sa.Enum("NORMAL", "INTERES_FIJO", name="prestamo_tipo")
    prestamo_tipo.create(bind, checkfirst=True)

    # Valores nuevos en enums que YA existían. No se usan en esta misma
    # transacción —Postgres no lo permite—: recién los escriben los servicios.
    op.execute("ALTER TYPE frecuencia_cuotas ADD VALUE IF NOT EXISTS 'CADA_30_DIAS'")
    op.execute("ALTER TYPE caja_categoria ADD VALUE IF NOT EXISTS 'DEVOLUCION_CAPITAL'")

    op.add_column(
        "prestamos",
        sa.Column(
            "tipo_prestamo",
            sa.Enum("NORMAL", "INTERES_FIJO", name="prestamo_tipo", create_type=False),
            nullable=False,
            server_default="NORMAL",
        ),
    )
    op.add_column("prestamos", sa.Column("monto_interes_fijo", sa.Numeric(18, 2), nullable=True))
    op.add_column("prestamos", sa.Column("dia_cobro", sa.Date(), nullable=True))
    op.add_column("prestamos", sa.Column("capital_pendiente", sa.Numeric(18, 2), nullable=True))

    op.create_index("ix_prestamos_tipo_prestamo", "prestamos", ["tipo_prestamo"])

    # `cuotas > 0` deja de valer tal cual: un préstamo a interés fijo no tiene
    # cuadro y guarda 0.
    op.drop_constraint("ck_prestamos_cuotas_positive", "prestamos", type_="check")
    op.create_check_constraint("ck_prestamos_cuotas_por_tipo", "prestamos", _CK_CUOTAS)
    op.create_check_constraint("ck_prestamos_interes_fijo_coherente", "prestamos", _CK_COHERENCIA)


def downgrade() -> None:
    # Volver atrás exige que no haya préstamos a interés fijo cargados: sin la
    # columna `tipo_prestamo` esas filas quedarían mezcladas con las normales,
    # con `cuotas = 0` y sin cuadro, y el panel las mostraría como préstamos
    # vacíos. Postgres fallaría igual al restaurar `cuotas > 0`, pero con un
    # error opaco; acá se dice qué pasa y cuál es la salida.
    #
    # Se cuentan también los anulados: anular es una marca (`anulado_at`), no un
    # DELETE (§Anulación), y la fila sigue ahí. Para bajar la migración hay que
    # borrarlas de verdad.
    op.execute(
        """
        DO $$
        DECLARE interes_fijo int;
        BEGIN
            SELECT count(*) INTO interes_fijo
              FROM prestamos WHERE tipo_prestamo = 'INTERES_FIJO';
            IF interes_fijo > 0 THEN
                RAISE EXCEPTION
                    'No se puede volver a 0030: hay % prestamo(s) a interes fijo '
                    '(anulados incluidos: anular no borra la fila). Borralos de la '
                    'tabla prestamos antes de bajar la migracion.', interes_fijo;
            END IF;
        END $$;
        """
    )

    op.drop_constraint("ck_prestamos_interes_fijo_coherente", "prestamos", type_="check")
    op.drop_constraint("ck_prestamos_cuotas_por_tipo", "prestamos", type_="check")
    op.create_check_constraint("ck_prestamos_cuotas_positive", "prestamos", "cuotas > 0")

    op.drop_index("ix_prestamos_tipo_prestamo", table_name="prestamos")
    op.drop_column("prestamos", "capital_pendiente")
    op.drop_column("prestamos", "dia_cobro")
    op.drop_column("prestamos", "monto_interes_fijo")
    op.drop_column("prestamos", "tipo_prestamo")
    sa.Enum(name="prestamo_tipo").drop(op.get_bind(), checkfirst=True)

    # Nota: no se quitan los valores agregados a `frecuencia_cuotas` ni a
    # `caja_categoria`. Postgres no soporta DROP VALUE en un enum, y recrear el
    # tipo obligaría a reescribir todas las columnas que lo usan. Quedan sin usar,
    # que es inocuo — mismo criterio que las migraciones 0016, 0020, 0023 y 0026.
