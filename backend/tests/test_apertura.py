"""Apertura del sistema: cartera preexistente y saldo inicial (régimen 2026-08-06).

El caso que estos tests protegen: al poner el sistema en marcha se carga la
cartera de cheques que YA se tenía. Si esas altas asentaran el egreso de compra,
se estaría restando plata que salió antes de que el sistema existiera —y que el
efectivo de apertura ya tiene descontada—, con lo cual se descontaría dos veces.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import CajaCategoria, CajaTipo, ConfiguracionApertura


class FakeDB:
    """Sesión mínima: `get` devuelve la configuración que se le programe."""

    def __init__(self, cfg: ConfiguracionApertura | None) -> None:
        self.cfg = cfg

    def get(self, _modelo, _pk):
        return self.cfg


def _cfg(fecha_corte: date | None) -> ConfiguracionApertura:
    return ConfiguracionApertura(id=1, fecha_corte_carga_inicial=fecha_corte)


# ── Fecha de corte ────────────────────────────────────────────────────

def test_sin_corte_definido_todo_es_operacion_normal() -> None:
    from app.services.apertura import es_carga_inicial

    # Sin apertura configurada el sistema opera como siempre: la compra descuenta.
    assert es_carga_inicial(FakeDB(None), date(2026, 8, 6)) is False
    assert es_carga_inicial(FakeDB(_cfg(None)), date(2026, 8, 6)) is False


def test_cheque_cargado_antes_del_corte_es_carga_inicial() -> None:
    from app.services.apertura import es_carga_inicial

    db = FakeDB(_cfg(date(2026, 8, 7)))
    assert es_carga_inicial(db, date(2026, 8, 6)) is True


def test_el_dia_del_corte_todavia_es_carga_inicial() -> None:
    from app.services.apertura import es_carga_inicial

    # El corte es inclusive: ese mismo día se sigue cargando cartera vieja.
    db = FakeDB(_cfg(date(2026, 8, 7)))
    assert es_carga_inicial(db, date(2026, 8, 7)) is True


def test_despues_del_corte_vuelve_a_descontar_de_caja() -> None:
    from app.services.apertura import es_carga_inicial

    db = FakeDB(_cfg(date(2026, 8, 7)))
    assert es_carga_inicial(db, date(2026, 8, 8)) is False


# ── Saldo de apertura ─────────────────────────────────────────────────

def test_saldo_definido_arranca_en_falso() -> None:
    assert _cfg(None).saldo_definido is False


def test_saldo_definido_es_true_al_fijarlo() -> None:
    from datetime import UTC, datetime

    cfg = _cfg(None)
    cfg.definido_at = datetime(2026, 8, 7, tzinfo=UTC)
    assert cfg.saldo_definido is True


def test_la_categoria_saldo_inicial_existe_y_es_ingreso() -> None:
    """El efectivo de apertura entra como INGRESO con su propia categoría, para
    que el reporte pueda tratarlo como saldo y no como ingreso del día."""
    assert CajaCategoria.SALDO_INICIAL.value == "SALDO_INICIAL"
    assert CajaTipo.INGRESO.value == "INGRESO"


def test_el_saldo_inicial_no_cuenta_como_ingreso_del_periodo() -> None:
    """Si el efectivo de arranque sumara a los ingresos, el día en que se carga
    aparecería con un ingreso enorme que nunca ocurrió ese día. Va al saldo de
    apertura, no al flujo del período."""
    from app.services.reportes import _GRUPO_POR_CATEGORIA, _LABEL_CATEGORIA

    # Tiene grupo propio, separado de COBROS: no se mezcla con la operación diaria.
    assert _GRUPO_POR_CATEGORIA[CajaCategoria.SALDO_INICIAL] == "APERTURA"
    assert _LABEL_CATEGORIA[CajaCategoria.SALDO_INICIAL] == "Saldo inicial de caja"


def test_saldo_de_apertura_se_calcula_con_signo_por_tipo() -> None:
    """El saldo previo suma ingresos y resta egresos: es la plata que quedó.

    Réplica en memoria de la agregación que hace `_saldo_hasta` en SQL, para fijar
    la regla de signos —que es donde un error pasa desapercibido y descuadra todo—.
    """
    movimientos = [
        (CajaTipo.INGRESO, Decimal("33000000.00")),  # saldo inicial
        (CajaTipo.EGRESO, Decimal("5000000.00")),    # compras del período previo
        (CajaTipo.INGRESO, Decimal("1200000.00")),   # cobros
    ]
    saldo = sum(
        (m if t == CajaTipo.INGRESO else -m for t, m in movimientos), Decimal("0.00")
    )
    assert saldo == Decimal("29200000.00")
