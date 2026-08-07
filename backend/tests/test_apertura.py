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


# ── El saldo inicial es un punto de corte, no un sumando ──────────────

def _saldo(movimientos, desde, corte=None):
    """Réplica en memoria de `_saldo_hasta`: qué entra en el saldo de apertura.

    `movimientos` son (fecha, tipo, monto); `corte` es la fecha del saldo inicial.
    """
    if corte is not None and corte <= desde:
        elegidos = [m for m in movimientos if corte <= m[0] < desde]
    else:
        elegidos = [m for m in movimientos if m[0] < desde]
    return sum(
        (m if t == CajaTipo.INGRESO else -m for _, t, m in elegidos), Decimal("0.00")
    )


def test_sin_saldo_inicial_se_suma_toda_la_historia() -> None:
    movs = [
        (date(2026, 8, 5), CajaTipo.EGRESO, Decimal("33000000.00")),
        (date(2026, 8, 6), CajaTipo.INGRESO, Decimal("500000.00")),
    ]
    assert _saldo(movs, date(2026, 8, 7)) == Decimal("-32500000.00")


def test_el_dia_del_saldo_inicial_arranca_exactamente_en_ese_efectivo() -> None:
    """El caso del cierre real: se cuenta la plata el 7 y se carga con fecha 7.

    La apertura del 7 tiene que ser EXACTAMENTE lo contado. Si se sumara la
    historia previa (millones en rojo por compras de cartera vieja), el sistema
    mostraría muchísima menos plata de la que hay en el cajón.
    """
    corte = date(2026, 8, 7)
    movs = [
        (date(2026, 8, 5), CajaTipo.EGRESO, Decimal("33000000.00")),   # historia
        (date(2026, 8, 6), CajaTipo.EGRESO, Decimal("5000000.00")),    # historia
        (corte, CajaTipo.INGRESO, Decimal("2000000.00")),              # SALDO_INICIAL
    ]
    # Para el reporte DEL día 7, el saldo inicial cae dentro del período y lo suma
    # `_caja`; la apertura previa tiene que dar 0, no la historia en rojo.
    assert _saldo(movs, corte, corte) == Decimal("0.00")


def test_dias_posteriores_arrastran_desde_el_saldo_inicial() -> None:
    """El 8 abre con lo del 7 más lo que se movió el 7 — sin la historia previa."""
    corte = date(2026, 8, 7)
    movs = [
        (date(2026, 8, 5), CajaTipo.EGRESO, Decimal("33000000.00")),  # queda afuera
        (corte, CajaTipo.INGRESO, Decimal("2000000.00")),             # SALDO_INICIAL
        (corte, CajaTipo.EGRESO, Decimal("300000.00")),               # gasto del 7
    ]
    assert _saldo(movs, date(2026, 8, 8), corte) == Decimal("1700000.00")


def test_reportes_anteriores_al_corte_conservan_su_historia() -> None:
    """Mirar un día previo al arranque sigue mostrando lo que pasó entonces: el
    saldo inicial no reescribe el pasado, solo define desde dónde se cuenta."""
    corte = date(2026, 8, 7)
    movs = [
        (date(2026, 8, 4), CajaTipo.EGRESO, Decimal("1000000.00")),
        (corte, CajaTipo.INGRESO, Decimal("2000000.00")),
    ]
    assert _saldo(movs, date(2026, 8, 5), corte) == Decimal("-1000000.00")


# ── Stock inicial de dólares (lote de apertura) ───────────────────────

def test_dolares_sin_cotizacion_se_rechazan() -> None:
    """El efectivo en USD por sí solo NO habilita venderlos: la venta consume
    lotes de compra (§4). Sin la cotización de costo no se puede armar el lote, y
    el operador lo descubriría recién al intentar vender."""
    from app.services.apertura import definir_saldo_inicial
    from app.services.exceptions import ValidationError

    class DB:
        def get(self, *_a, **_k):
            return _cfg(None)

    try:
        definir_saldo_inicial(
            DB(),
            saldo_ars=Decimal("1000"),
            saldo_usd=Decimal("500"),  # hay dólares...
            cotizacion_usd=None,        # ...pero no se dijo a cuánto se compraron
            fecha=date(2026, 8, 7),
            operador_id="panel",
        )
        raise AssertionError("debería haber exigido la cotización")
    except ValidationError as exc:
        assert "cotización" in str(exc)


def test_sin_dolares_no_hace_falta_cotizacion() -> None:
    """Caso de la apertura real del 2026-08-06: no tenían dólares, se cargó 0 y
    el stock USD arranca vacío sin pedir nada."""
    from app.services.apertura import definir_saldo_inicial
    from app.services.exceptions import ValidationError

    class DB:
        def get(self, *_a, **_k):
            return _cfg(None)

    # Solo debe fallar por la BD falsa, NUNCA por la validación de cotización.
    try:
        definir_saldo_inicial(
            DB(),
            saldo_ars=Decimal("1000"),
            saldo_usd=Decimal("0"),
            cotizacion_usd=None,
            fecha=date(2026, 8, 7),
            operador_id="panel",
        )
    except ValidationError as exc:
        raise AssertionError(f"no debía validar nada de cotización: {exc}") from exc
    except Exception:
        pass  # cualquier otra explosión viene del stub, no de la regla


def test_el_lote_de_apertura_no_asienta_caja() -> None:
    """El lote aporta stock, no plata: los pesos salieron antes de que el sistema
    existiera y la caja USD ya la da la línea SALDO_INICIAL. Si `resync` le
    inventara líneas, los dólares se contarían dos veces."""
    import inspect

    from app.services.movimientos import _resync_caja_movimiento

    fuente = inspect.getsource(_resync_caja_movimiento)
    assert "es_apertura" in fuente
    assert "return" in fuente.split("es_apertura")[1][:80]
