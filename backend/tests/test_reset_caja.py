"""Reset de caja: vaciar el libro sin perder lo que se debe.

Lo que se custodia acá es lo que hace que el reset **sirva**: que se lleve la
caja, que NO se lleve lo que el negocio tiene o debe, y sobre todo que mueva la
línea de corte. Sin esa última parte el reset deja una trampa: editar un cheque
o un préstamo viejo **rehace su asiento**, y ese egreso resucita dentro de la
caja recién estrenada sin que nada avise.

Estilo del proyecto: unitarios puros, sin BD.

Ver §Reset de caja.
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta

import pytest

from app.core.fechas import hoy_local
from app.services import apertura as svc_apertura
from app.services import deudas_simples as svc_deudas_simples
from app.services import pasivos as svc_pasivos
from app.services import prestamos as svc_prestamos
from app.services import reset_caja as svc_reset
from app.services.exceptions import ValidationError


# ══════════════════════════════════════════════════════════════════════
#  No se ejecuta por accidente
# ══════════════════════════════════════════════════════════════════════

def test_exige_la_frase_exacta() -> None:
    """Un `forzar=true` se manda por accidente desde cualquier cliente HTTP.

    Una frase escrita a mano, no. La diferencia entre un click de más y borrar
    el libro de caja de producción.
    """
    for intento in ("", "si", "true", "resetear", "RESETEAR", "BORRAR CAJA"):
        with pytest.raises(ValidationError):
            svc_reset.ejecutar(None, operador_id="pedro", confirmacion=intento)


def test_exige_operador() -> None:
    with pytest.raises(ValidationError):
        svc_reset.ejecutar(None, operador_id="  ", confirmacion=svc_reset.CONFIRMACION)


def test_la_frase_no_distingue_mayusculas_ni_espacios() -> None:
    """Escribirla en minúscula o con un espacio de más no puede ser un error:
    el que la está tipeando ya decidió, y hacerlo fallar solo invita a probar
    de nuevo hasta que salga."""
    fuente = inspect.getsource(svc_reset.ejecutar)
    assert ".strip().upper()" in fuente


# ══════════════════════════════════════════════════════════════════════
#  Qué se lleva y qué no
# ══════════════════════════════════════════════════════════════════════

def test_borra_todo_lo_que_es_caja() -> None:
    """El libro, los lotes de dólares, los ajustes y los gastos.

    Los dos últimos existen **solo** como movimiento de caja: conservarlos con
    su línea borrada los dejaría de adorno, sumando en ningún lado.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    for tabla in ("MovimientoCaja", "MovimientoEfectivo", "AjusteCaja", "GastoOperativo"):
        assert f"delete({tabla})" in fuente or f"update({tabla})" in fuente, tabla


def test_no_toca_lo_que_el_negocio_tiene_o_debe() -> None:
    """Cheques, préstamos, cuotas, fiados, deudas de clientes y pasivos.

    El pasivo se **modifica** (se le suelta el lote) pero no se borra: lo que se
    debe se sigue debiendo aunque la caja arranque de cero.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    for tabla in ("Cheque", "Prestamo", "Cuota", "Fiado", "DeudaSimple", "Compensacion"):
        assert f"delete({tabla})" not in fuente, tabla
    assert "delete(Pasivo)" not in fuente


def test_suelta_el_lote_del_pasivo_antes_de_borrarlo() -> None:
    """Los pasivos apuntan a su lote de stock por FK (§5).

    Sin soltar el vínculo primero, el DELETE de los lotes falla y el reset queda
    a medias: la caja borrada y los lotes vivos.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    i_update = fuente.index("update(Pasivo)")
    i_delete = fuente.index("delete(MovimientoEfectivo)")
    assert i_update < i_delete


def test_deja_la_apertura_sin_definir() -> None:
    """Los saldos viejos ya no describen nada.

    Dejarlos marcados haría que cargar los nuevos exija `forzar`, como si se
    estuviera corrigiendo un error en vez de arrancando de cero.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    assert "cfg.definido_at = None" in fuente
    assert "cfg.saldo_inicial_ars_transf = None" in fuente
    assert "cfg.saldo_inicial_usd_transf = None" in fuente


# ══════════════════════════════════════════════════════════════════════
#  La línea de corte — la parte que hace que el reset sirva
# ══════════════════════════════════════════════════════════════════════

def test_el_corte_queda_en_el_dia_anterior() -> None:
    """Lo que se cargue HOY después del reset tiene que descontar plata.

    Un corte puesto "hoy" dejaría todo el día del lado viejo: las compras reales
    de la jornada no sacarían un peso de la caja, y el descuadre aparecería
    recién al contar billetes.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    assert "hoy_local() - timedelta(days=1)" in fuente


def test_marca_lo_cargado_por_estado_y_no_por_fecha() -> None:
    """La línea la define el momento de apretar el botón, no una fecha elegida.

    Es lo que permite corregir la cartera a la mañana, resetear al mediodía y
    operar a la tarde: lo corregido queda del lado viejo y lo de la tarde
    descuenta normal. Filtrar por fecha obligaría a elegir un día y ahí es
    exactamente donde el operador se equivoca.
    """
    fuente = inspect.getsource(svc_reset._cheques_a_marcar)
    assert "anulado_at.is_(None)" in fuente
    assert "es_carga_inicial.is_(False)" in fuente
    # Sin condición de fecha: se marca TODO lo vivo.
    assert "fecha" not in fuente


def test_el_corte_alcanza_a_las_cuatro_familias() -> None:
    """Cheques, préstamos, deudas de clientes y pasivos rehacen su asiento al
    editarlos. Los cuatro tienen que consultar el corte, o corregir un dato menor
    resucita un egreso viejo dentro de la caja nueva."""
    assert "es_anterior_al_corte" in inspect.getsource(svc_prestamos.editar_prestamo)
    assert "es_anterior_al_corte" in inspect.getsource(
        svc_deudas_simples._registrar_egreso_origen
    )
    assert "es_anterior_al_corte" in inspect.getsource(svc_pasivos._registrar_ingreso)
    # El cheque ya lo resolvía con su marca propia (§Apertura).
    from app.services import cheques as svc_cheques

    assert "es_carga_inicial" in inspect.getsource(svc_cheques.resync_caja_cheque)


# ══════════════════════════════════════════════════════════════════════
#  El criterio del corte, en aislamiento
# ══════════════════════════════════════════════════════════════════════

class _FakeCfg:
    def __init__(self, corte: date | None) -> None:
        self.fecha_corte_carga_inicial = corte


class _FakeDB:
    def __init__(self, corte: date | None) -> None:
        self._cfg = _FakeCfg(corte)

    def get(self, _modelo, _pk):
        return self._cfg


def test_sin_corte_definido_todo_es_operacion_normal() -> None:
    """Un sistema recién puesto en marcha no tiene nada del lado viejo."""

    class _SinCfg:
        def get(self, _m, _p):
            return None

    assert svc_apertura.es_anterior_al_corte(_SinCfg(), hoy_local()) is False


def test_el_dia_del_corte_es_inclusive() -> None:
    """Mismo criterio que la cartera preexistente: hasta esa fecha, inclusive."""
    corte = date(2026, 8, 25)
    db = _FakeDB(corte)
    assert svc_apertura.es_anterior_al_corte(db, corte) is True
    assert svc_apertura.es_anterior_al_corte(db, corte - timedelta(days=1)) is True
    assert svc_apertura.es_anterior_al_corte(db, corte + timedelta(days=1)) is False


def test_el_corte_se_fija_aunque_no_hubiera_configuracion() -> None:
    """Con un `select` a secas, una base sin configuración dejaba el corte sin fijar.

    Los cheques quedaban marcados —tienen su marca propia— pero préstamos,
    deudas y pasivos volvían a asentar su egreso al editarlos: el agujero que
    este corte viene a tapar, reaparecido en silencio. Hallado en la revisión
    del 2026-08-25.
    """
    fuente = inspect.getsource(svc_reset.ejecutar)
    assert "get_configuracion(db)" in fuente
    assert "cfg = db.scalar(select(ConfiguracionApertura))" not in fuente
