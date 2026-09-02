"""Auto-reinicio de la sesión de WhatsApp: cuándo apretar y cuándo no.

Lo que estos tests protegen no es que el reinicio funcione —eso lo hace una
línea de HTTP—, es que **no se dispare cuando no corresponde**. Un reinicio
automático mal puesto es peor que la caída que arregla: reiniciar en loop una
sesión que pide QR no la recupera y arriesga el baneo del número, y reiniciar
una sesión sana corta conversaciones en curso a mitad de la mañana operativa.

Todo lo de acá es puro: la decisión, sin red ni reloj propio.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.autorestart import (
    Accion,
    EstadoReinicio,
    corresponde_mirar,
    decidir_reinicio,
)
from app.services.health import Chequeo, Diagnostico, Estado

T0 = datetime(2026, 9, 2, 9, 0, tzinfo=timezone.utc)


def _diag(*chequeos: Chequeo) -> Diagnostico:
    return Diagnostico(estado=Estado.OK, chequeos=chequeos, momento=T0)


# ── Qué estados disparan el reinicio ────────────────────────────────────────


def test_failed_pide_restart():
    accion, nuevo = decidir_reinicio(EstadoReinicio(), "FAILED", T0)
    assert accion is Accion.RESTART
    assert nuevo.intentos == 1
    assert nuevo.ultimo == T0


def test_stopped_pide_start_no_restart():
    """`STOPPED` es una sesión pausada: `start` la reanuda sin dar vuelta nada."""
    accion, _ = decidir_reinicio(EstadoReinicio(), "STOPPED", T0)
    assert accion is Accion.START


def test_scan_qr_no_se_toca():
    """El caso que NO hay que automatizar: sin celular no hay sesión que salvar."""
    accion, nuevo = decidir_reinicio(EstadoReinicio(), "SCAN_QR_CODE", T0)
    assert accion is Accion.NADA
    assert nuevo.intentos == 0


def test_sesion_sana_no_se_toca():
    for status in ("WORKING", "STARTING"):
        accion, _ = decidir_reinicio(EstadoReinicio(), status, T0)
        assert accion is Accion.NADA, status


def test_estado_desconocido_no_se_toca():
    """Lista blanca: una versión nueva de WAHA no activa el reinicio sola."""
    accion, _ = decidir_reinicio(EstadoReinicio(), "ALGO_NUEVO", T0)
    assert accion is Accion.NADA


def test_status_es_case_insensitive():
    accion, _ = decidir_reinicio(EstadoReinicio(), "failed", T0)
    assert accion is Accion.RESTART


# ── Los frenos ──────────────────────────────────────────────────────────────


def test_respeta_la_espera_entre_intentos():
    previo = EstadoReinicio(intentos=1, ultimo=T0)
    accion, nuevo = decidir_reinicio(
        previo, "FAILED", T0 + timedelta(minutes=2), espera=timedelta(minutes=5)
    )
    assert accion is Accion.NADA
    assert nuevo == previo  # no gasta intento


def test_reintenta_pasada_la_espera():
    previo = EstadoReinicio(intentos=1, ultimo=T0)
    ahora = T0 + timedelta(minutes=6)
    accion, nuevo = decidir_reinicio(previo, "FAILED", ahora, espera=timedelta(minutes=5))
    assert accion is Accion.RESTART
    assert nuevo.intentos == 2


def test_se_rinde_al_agotar_los_intentos():
    """Tres intentos y basta: reintentar sin techo arriesga el baneo del número."""
    estado = EstadoReinicio()
    ahora = T0
    for esperado in (1, 2, 3):
        accion, estado = decidir_reinicio(estado, "FAILED", ahora, max_intentos=3)
        assert accion is Accion.RESTART
        assert estado.intentos == esperado
        ahora += timedelta(minutes=6)

    accion, estado = decidir_reinicio(estado, "FAILED", ahora, max_intentos=3)
    assert accion is Accion.NADA
    assert estado.rendido is True


def test_rendido_no_avisa_dos_veces():
    """`rendido` marca el flanco: el aviso sale una vez, no en cada ciclo."""
    estado = EstadoReinicio(intentos=3, ultimo=T0, rendido=True)
    accion, nuevo = decidir_reinicio(estado, "FAILED", T0 + timedelta(hours=1), max_intentos=3)
    assert accion is Accion.NADA
    assert nuevo.rendido is True  # el monitor compara contra el previo


def test_recuperarse_devuelve_los_intentos():
    """La caída de la semana que viene arranca con el cupo entero."""
    agotado = EstadoReinicio(intentos=3, ultimo=T0, rendido=True)
    _, limpio = decidir_reinicio(agotado, "WORKING", T0 + timedelta(minutes=10))
    assert limpio == EstadoReinicio()

    accion, nuevo = decidir_reinicio(limpio, "FAILED", T0 + timedelta(days=7))
    assert accion is Accion.RESTART
    assert nuevo.intentos == 1


# ── Cuándo vale la pena ir a preguntarle a WAHA ─────────────────────────────


def test_no_consulta_si_la_sesion_esta_ok():
    diag = _diag(Chequeo("sesion_wa", Estado.OK, "conectada"))
    assert corresponde_mirar(diag) is False


def test_consulta_si_la_sesion_esta_caida():
    diag = _diag(Chequeo("sesion_wa", Estado.CAIDO, "la sesión falló"))
    assert corresponde_mirar(diag) is True


def test_no_consulta_si_waha_no_contesta():
    """Sin `sesion_wa` en el diagnóstico, WAHA está caído: no hay qué reiniciar."""
    diag = _diag(Chequeo("waha", Estado.CAIDO, "no responde"))
    assert corresponde_mirar(diag) is False


def test_configuracion_degradada_no_dispara_nada():
    """El estado normal del sistema es DEGRADADO por config: no es motivo."""
    diag = _diag(
        Chequeo("sesion_wa", Estado.OK, "conectada"),
        Chequeo("configuracion", Estado.DEGRADADO, "falta WHATSAPP_OPERATOR_PHONE"),
    )
    assert corresponde_mirar(diag) is False
