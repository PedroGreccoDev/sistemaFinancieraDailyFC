"""El export tiene que llevar TODAS las columnas de cada tabla.

Una columna que falta en estas listas no rompe nada al exportar: el JSON sale
igual, sin ella. El daño aparece al importar, y en silencio — la columna vuelve
en NULL o en su default. Ya pasó tres veces:

- `es_carga_inicial` (cheques): la cartera preexistente volvía como compra normal
  y al editarla se le asentaba el egreso que el régimen de apertura quita, o sea
  la plata descontada dos veces.
- `es_apertura` / `es_ajuste` (movimientos_efectivo): el lote de apertura volvía
  como compra real y se ganaba líneas de caja que nunca existieron.
- `medio_pago` / `cotizacion` (movimientos_caja): se perdía con qué se pagó cada
  pasivo y el $/USD de los pagos cross-moneda.

Por eso el test compara contra el modelo en vez de fijar una lista a mano: cuando
una migración agrega una columna, esto falla y obliga a decidir si va al backup.
"""

from __future__ import annotations

import pytest

from app.db.models import (
    AjusteCaja,
    Cheque,
    Cliente,
    Compensacion,
    CompensacionImputacion,
    Cuota,
    DeudaSimple,
    Fiado,
    GastoOperativo,
    MovimientoCaja,
    MovimientoEfectivo,
    Pasivo,
    Prestamo,
)
from app.services import backup

# (nombre de la lista, lista de columnas exportadas, modelo)
_TABLAS = [
    ("_CL", backup._CL, Cliente),
    ("_CH", backup._CH, Cheque),
    ("_PR", backup._PR, Prestamo),
    ("_CU", backup._CU, Cuota),
    ("_MO", backup._MO, MovimientoEfectivo),
    ("_FI", backup._FI, Fiado),
    ("_PA", backup._PA, Pasivo),
    ("_GA", backup._GA, GastoOperativo),
    ("_DS", backup._DS, DeudaSimple),
    ("_MC", backup._MC, MovimientoCaja),
    ("_AJ", backup._AJ, AjusteCaja),
    ("_CO", backup._CO, Compensacion),
    ("_CI", backup._CI, CompensacionImputacion),
]


@pytest.mark.parametrize(("nombre", "columnas", "modelo"), _TABLAS)
def test_el_export_lleva_todas_las_columnas(nombre: str, columnas: list, modelo: type) -> None:
    del_modelo = {c.name for c in modelo.__table__.columns}
    faltantes = sorted(del_modelo - set(columnas))
    assert not faltantes, (
        f"{nombre} no exporta {faltantes}. Si la columna tiene que viajar en el "
        f"backup, agregala; un import la devolvería en NULL sin avisar."
    )


@pytest.mark.parametrize(("nombre", "columnas", "modelo"), _TABLAS)
def test_el_export_no_declara_columnas_inexistentes(nombre: str, columnas: list, modelo: type) -> None:
    del_modelo = {c.name for c in modelo.__table__.columns}
    sobrantes = sorted(set(columnas) - del_modelo)
    assert not sobrantes, f"{nombre} declara columnas que el modelo no tiene: {sobrantes}."


def test_las_columnas_decimales_del_backup_se_deserializan_como_decimal() -> None:
    """Un Decimal viaja como string en el JSON. Si la columna no está en
    `_DEC_COLS`, el import la inserta como texto: Postgres lo acepta y el
    descuadre recién se nota al sumar la caja."""
    for col in ("cotizacion", "cotizacion_usd", "cotizacion_pago", "cotizacion_aplicada"):
        assert col in backup._DEC_COLS, f"`{col}` tiene que estar en _DEC_COLS."


# ── Columnas de plata ─────────────────────────────────────────────────

@pytest.mark.parametrize(("nombre", "columnas", "modelo"), _TABLAS)
def test_toda_columna_numerica_esta_en_dec_cols(
    nombre: str, columnas: list, modelo: type
) -> None:
    """Una columna Numeric que no esté en `_DEC_COLS` se importa como TEXTO.

    El export la escribe como string (así viaja un Decimal en JSON) y el import
    la inserta tal cual si no sabe que hay que reconstruirla: la fila entra, no
    falla nada, y el descuadre recién se nota al sumar la caja. Igual que con las
    listas de columnas, esto se compara contra el modelo para que una migración
    nueva obligue a decidir.
    """
    import sqlalchemy as sa

    numericas = {
        c.name
        for c in modelo.__table__.columns
        if isinstance(c.type, sa.Numeric) and c.name in columnas
    }
    faltantes = sorted(numericas - backup._DEC_COLS)
    assert not faltantes, (
        f"{nombre} exporta {faltantes} como Decimal pero `_DEC_COLS` no las "
        f"reconoce: el import las guardaría como texto."
    )
