"""Capa de salud: diagnóstico de las piezas del bot y decisión de alertar.

El caso que estos tests protegen: el día que el bot se cae, la alerta tiene que
llegar —y tiene que decir QUÉ se rompió—. Y el resto de los días **no tiene que
llegar nada**: una alerta que suena por un timeout suelto se vuelve ruido, se
ignora, y la próxima caída real se entera el cliente primero.

Todo lo que se testea acá es puro (sin BD ni red): la interpretación de la
respuesta de WAHA y la máquina de decisión del monitor.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.services.health import (
    Chequeo,
    Diagnostico,
    Estado,
    EstadoAlerta,
    combinar,
    decidir_alerta,
    interpretar_sesion,
    interpretar_webhook,
)

T0 = datetime(2026, 8, 13, 15, 0, tzinfo=timezone.utc)


def _diag(estado: Estado, *chequeos: Chequeo, momento: datetime = T0) -> Diagnostico:
    return Diagnostico(estado=estado, chequeos=chequeos, momento=momento)


def _caido(nombre: str = "sesion_wa") -> Diagnostico:
    c = Chequeo(nombre, Estado.CAIDO, "no responde")
    return _diag(Estado.CAIDO, c)


# ── Interpretación del estado de la sesión de WAHA ─────────────────────

def test_sesion_working_es_ok() -> None:
    assert interpretar_sesion("WORKING").estado is Estado.OK


def test_sesion_pidiendo_qr_es_caida() -> None:
    # El caso real: el celular se desvinculó y el bot dejó de recibir mensajes.
    chequeo = interpretar_sesion("SCAN_QR_CODE")
    assert chequeo.estado is Estado.CAIDO
    assert "QR" in chequeo.detalle  # la alerta tiene que decir qué hacer


def test_sesion_detenida_o_fallada_es_caida() -> None:
    assert interpretar_sesion("STOPPED").estado is Estado.CAIDO
    assert interpretar_sesion("FAILED").estado is Estado.CAIDO


def test_sesion_arrancando_es_degradada_no_caida() -> None:
    # STARTING es transitorio: alertar como caída dispararía falsos positivos
    # en cada deploy.
    assert interpretar_sesion("STARTING").estado is Estado.DEGRADADO


def test_estado_desconocido_no_se_da_por_bueno() -> None:
    # Una versión nueva de WAHA con otro estado: avisar, pero sin gritar "caído".
    chequeo = interpretar_sesion("ALGO_NUEVO")
    assert chequeo.estado is Estado.DEGRADADO


# ── El webhook: la caída silenciosa ────────────────────────────────────

def test_sin_webhooks_es_caida() -> None:
    # Sesión WORKING pero WAHA sin webhook = el bot no recibe un solo mensaje
    # y desde afuera parece sano. Es la caída que nadie detecta.
    chequeo = interpretar_webhook({"webhooks": []}, "https://app.test/webhook/whatsapp")
    assert chequeo.estado is Estado.CAIDO


def test_webhook_apuntando_a_otro_lado_es_degradado() -> None:
    config = {"webhooks": [{"url": "https://viejo.test/webhook/whatsapp"}]}
    chequeo = interpretar_webhook(config, "https://app.test/webhook/whatsapp")
    assert chequeo.estado is Estado.DEGRADADO
    assert "viejo.test" in chequeo.detalle


def test_webhook_correcto_es_ok() -> None:
    config = {"webhooks": [{"url": "https://app.test/webhook/whatsapp", "events": ["message"]}]}
    assert interpretar_webhook(config, "https://app.test/webhook/whatsapp").estado is Estado.OK


def test_sin_datos_de_webhook_no_inventa_una_caida() -> None:
    # Otra versión de WAHA que no devuelve `config`: no hay nada que verificar,
    # y asumir lo peor sería una alerta falsa permanente.
    assert interpretar_webhook(None, "https://app.test/webhook/whatsapp").estado is Estado.OK
    assert interpretar_webhook({}, "https://app.test/webhook/whatsapp").estado is Estado.OK


def test_url_esperada_vacia_no_compara() -> None:
    # Sin PUBLIC_BASE_URL configurada no se puede saber cuál es la URL correcta.
    config = {"webhooks": [{"url": "https://cualquiera.test/webhook/whatsapp"}]}
    assert interpretar_webhook(config, "").estado is Estado.OK


# ── Estado global ──────────────────────────────────────────────────────

def test_el_estado_global_es_el_peor_chequeo() -> None:
    chequeos = [
        Chequeo("base_datos", Estado.OK, ""),
        Chequeo("waha", Estado.DEGRADADO, ""),
        Chequeo("sesion_wa", Estado.CAIDO, ""),
    ]
    assert combinar(chequeos) is Estado.CAIDO
    assert combinar(chequeos[:2]) is Estado.DEGRADADO
    assert combinar([]) is Estado.OK


# ── Decisión de alertar ────────────────────────────────────────────────

def test_no_alerta_al_primer_fallo() -> None:
    # Un timeout suelto de WAHA se recupera solo; alertar por eso entrena al
    # dueño a ignorar las alertas.
    decision = decidir_alerta(EstadoAlerta(), _caido())
    assert decision.aviso is None
    assert decision.estado.fallos_consecutivos == 1


def test_alerta_al_segundo_fallo_consecutivo_con_el_motivo() -> None:
    previo = decidir_alerta(EstadoAlerta(), _caido()).estado
    decision = decidir_alerta(previo, _caido())

    assert decision.aviso is not None
    assert "sesion_wa" in decision.aviso  # la alerta dice qué pieza falló
    assert decision.estado.firma_notificada == "sesion_wa:CAIDO"


def test_no_repite_la_misma_alerta_en_cada_chequeo() -> None:
    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado

    # Sigue caído dos minutos después: no se vuelve a avisar.
    luego = _diag(
        Estado.CAIDO,
        Chequeo("sesion_wa", Estado.CAIDO, "no responde"),
        momento=T0 + timedelta(minutes=2),
    )
    assert decidir_alerta(estado, luego).aviso is None


def test_recuerda_la_caida_abierta_pasada_la_ventana() -> None:
    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado

    tarde = _diag(
        Estado.CAIDO,
        Chequeo("sesion_wa", Estado.CAIDO, "no responde"),
        momento=T0 + timedelta(minutes=31),
    )
    decision = decidir_alerta(estado, tarde, repetir_cada=timedelta(minutes=30))
    assert decision.aviso is not None
    assert "sigue igual" in decision.aviso


def test_si_se_rompe_otra_cosa_avisa_enseguida() -> None:
    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado

    # Ahora además se cayó la base: es información nueva, no espera la ventana.
    peor = _diag(
        Estado.CAIDO,
        Chequeo("sesion_wa", Estado.CAIDO, "no responde"),
        Chequeo("base_datos", Estado.CAIDO, "no responde"),
        momento=T0 + timedelta(minutes=2),
    )
    decision = decidir_alerta(estado, peor)
    assert decision.aviso is not None
    assert "base_datos" in decision.aviso


def test_avisa_la_recuperacion_solo_si_habia_alerta_abierta() -> None:
    ok = _diag(Estado.OK, Chequeo("sesion_wa", Estado.OK, "conectada"))

    # Sin alerta previa no hay nada que anunciar.
    assert decidir_alerta(EstadoAlerta(), ok).aviso is None

    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado
    decision = decidir_alerta(estado, ok)
    assert decision.recuperado is True
    assert "RECUPERADO" in decision.aviso
    assert decision.estado == EstadoAlerta()  # queda listo para la próxima caída


def test_un_fallo_aislado_entre_chequeos_ok_no_alerta() -> None:
    ok = _diag(Estado.OK, Chequeo("sesion_wa", Estado.OK, "conectada"))
    estado = EstadoAlerta()
    estado = decidir_alerta(estado, _caido()).estado  # 1 fallo
    estado = decidir_alerta(estado, ok).estado  # se recuperó solo
    decision = decidir_alerta(estado, _caido())  # vuelve a fallar: cuenta de cero

    assert decision.aviso is None
    assert decision.estado.fallos_consecutivos == 1


def test_degradado_tambien_alerta() -> None:
    # Un webhook apuntando a otro lado no se arregla solo: hay que enterarse.
    degradado = _diag(Estado.DEGRADADO, Chequeo("webhook_wa", Estado.DEGRADADO, "otra url"))
    estado = decidir_alerta(EstadoAlerta(), degradado).estado
    decision = decidir_alerta(estado, degradado)

    assert decision.aviso is not None
    assert "DEGRADADO" in decision.aviso
