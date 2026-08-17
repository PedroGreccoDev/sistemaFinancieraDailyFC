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

from types import SimpleNamespace

import app.services.health as health_mod
from app.services.health import (
    Chequeo,
    Diagnostico,
    Estado,
    EstadoAlerta,
    chequear_configuracion,
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


def test_webhook_apuntando_a_otra_cosa_es_degradado() -> None:
    # Hay webhook, pero no al bot: los mensajes de WhatsApp no llegan.
    config = {"webhooks": [{"url": "https://otro-sistema.test/api/eventos"}]}
    chequeo = interpretar_webhook(config, "https://app.test/webhook/whatsapp")
    assert chequeo.estado is Estado.DEGRADADO


def test_webhook_correcto_es_ok() -> None:
    config = {"webhooks": [{"url": "https://app.test/webhook/whatsapp", "events": ["message"]}]}
    assert interpretar_webhook(config, "https://app.test/webhook/whatsapp").estado is Estado.OK


def test_webhook_por_la_red_interna_de_railway_es_ok() -> None:
    # En el monorepo de Railway, WAHA puede apuntar legítimamente al host interno
    # en vez del dominio público. Compararlo contra PUBLIC_BASE_URL daría una
    # alerta falsa cada 30 minutos, que es como se arruina un sistema de alertas.
    config = {"webhooks": [{"url": "http://backend.railway.internal:8000/webhook/whatsapp"}]}
    assert interpretar_webhook(config, "https://app.up.railway.app/webhook/whatsapp").estado is Estado.OK


def test_sin_datos_de_webhook_no_inventa_una_caida() -> None:
    # Otra versión de WAHA que no devuelve `config`: no hay nada que verificar,
    # y asumir lo peor sería una alerta falsa permanente.
    assert interpretar_webhook(None, "https://app.test/webhook/whatsapp").estado is Estado.OK
    assert interpretar_webhook({}, "https://app.test/webhook/whatsapp").estado is Estado.OK


def test_url_esperada_vacia_no_compara() -> None:
    # Sin PUBLIC_BASE_URL configurada no se puede saber cuál es la URL correcta.
    config = {"webhooks": [{"url": "https://cualquiera.test/webhook/whatsapp"}]}
    assert interpretar_webhook(config, "").estado is Estado.OK


# ── Configuración: la severidad va por consecuencia, no por variable ───

def _config(monkeypatch, **faltantes: bool) -> Chequeo:
    """Corre `chequear_configuracion` con las env vars que se indiquen vacías."""
    settings = SimpleNamespace(
        anthropic_api_key="" if faltantes.get("anthropic") else "sk-ant-x",
        whatsapp_operator_phone="" if faltantes.get("operador") else "5491100000000",
        openai_api_key="" if faltantes.get("openai") else "sk-oai-x",
    )
    monkeypatch.setattr(health_mod, "get_settings", lambda: settings)
    chequeos = chequear_configuracion()
    assert len(chequeos) == 1
    return chequeos[0]


def test_configuracion_completa_es_ok(monkeypatch) -> None:
    assert _config(monkeypatch).estado is Estado.OK


def test_sin_anthropic_es_caida(monkeypatch) -> None:
    # Sin la key el bot no interpreta un solo mensaje: eso sí es estar caído.
    assert _config(monkeypatch, anthropic=True).estado is Estado.CAIDO


def test_sin_numero_de_operador_es_degradado_no_caida(monkeypatch) -> None:
    # El caso que generaba la alerta falsa: con WHATSAPP_OPERATOR_PHONE vacía el
    # webhook NO filtra (`if operator_phone and ...`), así que el bot funciona
    # perfecto — pero le obedece a cualquiera. Marcarlo CAIDO ponía /health/deep
    # en 503 y el watchdog externo gritaba "bot caído" cada 5 minutos.
    chequeo = _config(monkeypatch, operador=True)
    assert chequeo.estado is Estado.DEGRADADO
    assert "CUALQUIER" in chequeo.detalle  # el detalle dice el riesgo real


def test_sin_openai_solo_pierde_los_audios(monkeypatch) -> None:
    chequeo = _config(monkeypatch, openai=True)
    assert chequeo.estado is Estado.DEGRADADO
    assert "audios" in chequeo.detalle


def test_reporta_todas_las_carencias_no_solo_la_peor(monkeypatch) -> None:
    # Enterarse de la segunda variable recién después de arreglar la primera es
    # un viaje extra al deploy.
    chequeo = _config(monkeypatch, anthropic=True, operador=True, openai=True)
    assert chequeo.estado is Estado.CAIDO  # la peor manda en el estado global
    assert "ANTHROPIC_API_KEY" in chequeo.detalle
    assert "WHATSAPP_OPERATOR_PHONE" in chequeo.detalle
    assert "OPENAI_API_KEY" in chequeo.detalle


def test_numero_de_operador_en_blanco_cuenta_como_faltante(monkeypatch) -> None:
    settings = SimpleNamespace(
        anthropic_api_key="sk-ant-x", whatsapp_operator_phone="   ", openai_api_key="sk-oai-x"
    )
    monkeypatch.setattr(health_mod, "get_settings", lambda: settings)
    assert chequear_configuracion()[0].estado is Estado.DEGRADADO


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


def test_el_resumen_sin_token_no_filtra_el_detalle() -> None:
    # Los detalles cuentan a qué URL apunta el webhook y qué host de Postgres no
    # contesta: van solo con HEALTH_TOKEN válido. Sin token se ve el estado, que
    # es lo que un monitor de uptime necesita, y nada más.
    diagnostico = _diag(
        Estado.CAIDO,
        Chequeo("base_datos", Estado.CAIDO, "no responde (OperationalError)"),
        Chequeo("webhook_wa", Estado.OK, "1 webhook(s) configurado(s)"),
    )

    resumen = diagnostico.to_dict(detallado=False)
    assert resumen["estado"] == "CAIDO"
    assert [c["nombre"] for c in resumen["chequeos"]] == ["base_datos", "webhook_wa"]
    assert all("detalle" not in c for c in resumen["chequeos"])

    completo = diagnostico.to_dict()
    assert completo["chequeos"][0]["detalle"] == "no responde (OperationalError)"


def test_token_de_health_se_compara_en_tiempo_constante() -> None:
    from app.api.routes.health import _token_ok

    assert _token_ok("secreto", (None, "secreto")) is True
    assert _token_ok("secreto", ("secreto", None)) is True
    assert _token_ok("secreto", (None, None)) is False
    assert _token_ok("secreto", ("otro", "tampoco")) is False
    # Un prefijo correcto no alcanza (lo que un `startswith` dejaría pasar).
    assert _token_ok("secreto", ("secret",)) is False


def _degradado(minutos: int = 0) -> Diagnostico:
    return _diag(
        Estado.DEGRADADO,
        Chequeo("configuracion", Estado.DEGRADADO, "falta el número del operador"),
        momento=T0 + timedelta(minutes=minutos),
    )


def test_un_degradado_no_molesta_a_nadie() -> None:
    # Lo que pidió el dueño: avisame cuando se cae y cuando se levanta, nada más.
    # Config pendiente deja el estado DEGRADADO por semanas; un mensaje por eso
    # —aunque sea uno solo por deploy— es ruido que él no pidió.
    estado = EstadoAlerta()
    for m in (0, 2, 35, 600):
        decision = decidir_alerta(estado, _degradado(m))
        estado = decision.estado
        assert decision.aviso is None


def test_el_degradado_se_puede_encender_y_avisa_una_sola_vez() -> None:
    # MONITOR_ALERTAR_DEGRADADO=true devuelve el aviso, pero nunca el
    # recordatorio periódico: repetirlo cada 30 min durante semanas es
    # exactamente cómo se aprende a ignorar el canal.
    estado = EstadoAlerta()
    for m in (0, 2):
        decision = decidir_alerta(estado, _degradado(m), alertar_degradado=True)
        estado = decision.estado
    assert decision.aviso is not None
    assert "DEGRADADO" in decision.aviso

    for m in (35, 70, 600):
        decision = decidir_alerta(estado, _degradado(m), alertar_degradado=True)
        estado = decision.estado
        assert decision.aviso is None


def test_avisa_que_volvio_aunque_siga_degradado() -> None:
    # El bug que esto fija: con las env vars de config sin definir, el estado
    # normal es DEGRADADO y NUNCA OK. Atado a OK, el aviso de "volvió" no salía
    # jamás — se caía WAHA (🔴 llegaba), volvía WAHA, y el 🟢 quedaba esperando
    # un OK que no existe. La mitad de lo pedido, y la que uno espera despierto.
    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado

    decision = decidir_alerta(estado, _degradado(20))
    assert decision.recuperado is True
    assert "RECUPERADO" in decision.aviso
    # Y no miente: dice qué quedó pendiente en vez de "todo perfecto".
    assert "configuracion" in decision.aviso
    assert decision.estado == EstadoAlerta()  # listo para la próxima caída


def test_un_degradado_solo_no_dispara_falsa_recuperacion() -> None:
    # Sin caída previa no hay nada que anunciar: el degradado no es un evento.
    assert decidir_alerta(EstadoAlerta(), _degradado()).aviso is None


def test_una_caida_si_insiste_hasta_que_se_arregle() -> None:
    # La contracara: con el bot muerto el recordatorio es justamente el punto.
    estado = EstadoAlerta()
    for _ in range(2):
        estado = decidir_alerta(estado, _caido()).estado

    tarde = _diag(
        Estado.CAIDO,
        Chequeo("sesion_wa", Estado.CAIDO, "no responde"),
        momento=T0 + timedelta(minutes=31),
    )
    assert decidir_alerta(estado, tarde).aviso is not None


def test_ignorar_el_degradado_no_es_dejar_de_mirar() -> None:
    # Callarse los degradados no puede tapar la caída que venga después: desde
    # un degradado de meses, si se cae WAHA la alerta sale igual (con el umbral
    # normal de dos ciclos, que es lo que filtra el timeout transitorio).
    estado = EstadoAlerta()
    for m in (0, 2, 4):
        estado = decidir_alerta(estado, _degradado(m)).estado
    assert estado.fallos_consecutivos == 0  # el degradado no acumula nada

    caido = _diag(
        Estado.CAIDO,
        Chequeo("sesion_wa", Estado.CAIDO, "no responde"),
        Chequeo("configuracion", Estado.DEGRADADO, "falta el número del operador"),
        momento=T0 + timedelta(minutes=6),
    )
    assert decidir_alerta(estado, caido).aviso is None  # primer fallo: espera
    estado = decidir_alerta(estado, caido).estado

    decision = decidir_alerta(estado, caido)
    assert decision.aviso is not None
    assert "sesion_wa" in decision.aviso


def test_la_recuperacion_de_un_degradado_se_avisa_igual() -> None:
    # Con el aviso de degradado encendido, su recuperación también se anuncia.
    estado = EstadoAlerta()
    for m in (0, 2):
        estado = decidir_alerta(estado, _degradado(m), alertar_degradado=True).estado

    ok = _diag(Estado.OK, Chequeo("configuracion", Estado.OK, "completa"), momento=T0 + timedelta(hours=5))
    decision = decidir_alerta(estado, ok, alertar_degradado=True)
    assert decision.recuperado is True
