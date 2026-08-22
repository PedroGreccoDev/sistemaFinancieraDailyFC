"""Motor de IA conmutable: qué proveedor atiende cada camino (§Bot).

Unitario puro: no se llama a ninguna API. Lo que se custodia acá es el ruteo y
—sobre todo— que los dos motores compartan **el mismo** system prompt: si cada
uno llevara su copia, una corrección de reglas de negocio aplicada en uno
dejaría al otro con la regla vieja, y la diferencia recién se notaría en una
operación mal cargada.
"""

from __future__ import annotations

import asyncio
import inspect
from types import SimpleNamespace

from app.services.ia import claude, contrato, motor, openai_engine


def _settings(monkeypatch, texto: str = "anthropic", ocr: str = "anthropic") -> None:
    monkeypatch.setattr(
        motor,
        "get_settings",
        lambda: SimpleNamespace(ia_provider_texto=texto, ia_provider_ocr=ocr),
    )


# ── Ruteo por camino ───────────────────────────────────────────────────

def test_default_es_claude_en_los_dos_caminos(monkeypatch) -> None:
    """Un deploy sin tocar env vars NO cambia de motor solo."""
    _settings(monkeypatch)
    assert motor.motor_texto() is claude
    assert motor.motor_ocr() is claude


def test_texto_y_ocr_se_eligen_por_separado(monkeypatch) -> None:
    """El caso de la prueba: los mensajes por OpenAI, las fotos en Claude.

    Se eligen por separado porque son dos trabajos con riesgos opuestos — un
    error de OCR no da ninguna señal, uno de texto se ve en el acto — y
    mezclarlos en una sola variable haría imposible saber cuál motor cambió el
    comportamiento."""
    _settings(monkeypatch, texto="openai", ocr="anthropic")
    assert motor.motor_texto() is openai_engine
    assert motor.motor_ocr() is claude


def test_un_typo_en_la_env_var_no_deja_al_bot_sin_motor(monkeypatch) -> None:
    """Cae al default y lo loguea: un typo en Railway no puede dejar a la
    financiera sin poder cargar una operación."""
    _settings(monkeypatch, texto="opnai", ocr="")
    assert motor.motor_texto() is claude
    assert motor.motor_ocr() is claude


def test_el_nombre_del_proveedor_no_distingue_mayusculas(monkeypatch) -> None:
    _settings(monkeypatch, texto="  OpenAI  ")
    assert motor.motor_texto() is openai_engine


def test_la_foto_rutea_por_el_camino_ocr(monkeypatch) -> None:
    """La señal de ruteo es la misma que usan los motores por dentro para
    elegir modelo: si viene una imagen, es OCR."""
    _settings(monkeypatch, texto="openai", ocr="anthropic")
    llamados: list[str] = []

    def _fake(nombre):
        async def _f(text, image_bytes, history, media_mime_type="image/jpeg"):
            llamados.append(nombre)
            return contrato.IntentResult(intent="DESCONOCIDO")

        return _f

    monkeypatch.setattr(claude, "extraer_intencion", _fake("anthropic"))
    monkeypatch.setattr(openai_engine, "extraer_intencion", _fake("openai"))

    asyncio.run(motor.extraer_intencion("cobré 100 lucas", None, []))
    asyncio.run(motor.extraer_intencion("", b"\x89PNG", []))

    assert llamados == ["openai", "anthropic"]


def test_la_confirmacion_va_por_el_motor_de_texto(monkeypatch) -> None:
    """Interpretar un "dale" es leer texto escrito: va con el motor de texto,
    aunque la operación pendiente haya entrado por una foto."""
    _settings(monkeypatch, texto="openai", ocr="anthropic")

    async def _confirm(text):
        return "confirm"

    monkeypatch.setattr(openai_engine, "clasificar_confirmacion", _confirm)
    assert asyncio.run(motor.clasificar_confirmacion("dale")) == "confirm"


# ── El prompt es uno solo ──────────────────────────────────────────────

def test_los_dos_motores_usan_el_mismo_system_prompt() -> None:
    assert claude._SYSTEM_PROMPT is contrato._SYSTEM_PROMPT
    assert openai_engine._SYSTEM_PROMPT is contrato._SYSTEM_PROMPT
    assert claude.INTENTS is openai_engine.INTENTS


def test_ningun_motor_define_su_propio_prompt() -> None:
    """El prompt tiene que estar en `contrato.py` y en ningún otro lado.

    Un motor que se copiara el prompt para "ajustarlo un poco" arrancaría igual
    y después se iría separando sin que nada falle."""
    for modulo in (claude, openai_engine):
        fuente = inspect.getsource(modulo)
        assert "_SYSTEM_PROMPT = " not in fuente, modulo.__name__


def test_la_fecha_de_hoy_no_va_en_el_system_prompt() -> None:
    """Vale para los dos motores: los dos cachean por PREFIJO, así que la fecha
    adentro del system tiraría el caché en cada cambio de día — en silencio,
    sin error, solo más caro. Por eso viaja en el mensaje."""
    assert "Hoy es" not in contrato._SYSTEM_PROMPT


# ── Contrato compartido ────────────────────────────────────────────────

def test_los_dos_motores_exponen_la_misma_interfaz() -> None:
    """Lo que el webhook le pide a `motor` tiene que existir en los dos, con la
    misma firma: si divergen, cambiar de proveedor rompe recién en producción."""
    for nombre in ("extraer_intencion", "clasificar_confirmacion"):
        firma_claude = inspect.signature(getattr(claude, nombre))
        firma_openai = inspect.signature(getattr(openai_engine, nombre))
        assert firma_claude == firma_openai, nombre


def test_el_resultado_es_el_mismo_tipo_en_los_dos() -> None:
    assert claude.IntentResult is contrato.IntentResult
    assert openai_engine.IntentResult is contrato.IntentResult


# ── Armado del mensaje de OpenAI ───────────────────────────────────────

def test_la_foto_va_como_data_uri_con_su_mime() -> None:
    contenido = openai_engine._contenido_usuario("", b"abc", "image/png")
    assert contenido[0]["type"] == "image_url"
    assert contenido[0]["image_url"]["url"].startswith("data:image/png;base64,")


def test_un_mime_raro_cae_en_jpeg() -> None:
    """WAHA a veces manda un mime que la API no acepta; mejor intentarlo como
    JPEG que perder la foto del cheque."""
    contenido = openai_engine._contenido_usuario("", b"abc", "image/heic")
    assert contenido[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_el_mensaje_de_texto_lleva_la_fecha_de_hoy_adelante() -> None:
    contenido = openai_engine._contenido_usuario("cobré 100 lucas", None, "image/jpeg")
    assert len(contenido) == 1
    assert contenido[0]["text"].startswith("(Hoy es ")
    assert "cobré 100 lucas" in contenido[0]["text"]


def test_una_respuesta_sin_texto_no_revienta() -> None:
    """Un modelo con razonamiento que agota el tope razonando devuelve
    `content` vacío o None, sin lanzar: hay que tratarlo como falla dura, no
    dejar que explote al llamar `.strip()` sobre None."""
    vacio = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None))])
    assert openai_engine._texto_de(vacio) == ""
    assert openai_engine._texto_de(SimpleNamespace(choices=[])) == ""


# ── El clasificador de confirmaciones ──────────────────────────────────

class _RespuestaFalsa:
    """Lo mínimo que `clasificar_confirmacion` le pide a una respuesta."""

    def __init__(self, contenido: str | None) -> None:
        self.choices = [SimpleNamespace(message=SimpleNamespace(content=contenido))]
        self.usage = SimpleNamespace(completion_tokens=0)


def _cliente_falso(monkeypatch, contenido: str | None):
    """Instala un cliente que no llama a nadie y guarda los kwargs recibidos."""
    visto: dict = {}

    async def _create(**kwargs):
        visto.update(kwargs)
        return _RespuestaFalsa(contenido)

    monkeypatch.setattr(
        openai_engine,
        "_get_client",
        lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=_create))),
    )
    monkeypatch.setattr(
        openai_engine,
        "get_settings",
        lambda: SimpleNamespace(openai_effort_confirmacion="minimal"),
    )
    monkeypatch.setattr(openai_engine, "_modelos", lambda: ("m-ocr", "m-texto", "m-confirm"))
    return visto


def test_el_tope_del_clasificador_deja_lugar_al_razonamiento(monkeypatch) -> None:
    """El veredicto es una palabra, pero el tope cubre razonamiento + respuesta.

    Con un cap ajustado al veredicto, un modelo que razona se lo come pensando y
    devuelve `content` vacío: eso sale por `unclear`, y `unclear` le **cancela la
    operación** al operador. Pasó en producción con el cap en 16."""
    visto = _cliente_falso(monkeypatch, "confirm")
    assert asyncio.run(openai_engine.clasificar_confirmacion("confirmá esos 3")) == "confirm"
    assert visto["max_completion_tokens"] >= 256


def test_el_clasificador_manda_el_esfuerzo_configurado(monkeypatch) -> None:
    visto = _cliente_falso(monkeypatch, "confirm")
    asyncio.run(openai_engine.clasificar_confirmacion("dale"))
    assert visto["reasoning_effort"] == "minimal"


def test_un_esfuerzo_vacio_no_manda_el_parametro(monkeypatch) -> None:
    """Igual que en la extracción: un modelo sin razonamiento lo rechaza."""
    visto = _cliente_falso(monkeypatch, "confirm")
    monkeypatch.setattr(
        openai_engine, "get_settings", lambda: SimpleNamespace(openai_effort_confirmacion="")
    )
    asyncio.run(openai_engine.clasificar_confirmacion("dale"))
    assert "reasoning_effort" not in visto


def test_un_veredicto_vacio_cae_en_other_y_se_loguea(monkeypatch, caplog) -> None:
    """Si el modelo no contesta, el mensaje se procesa como uno nuevo en vez de
    darse por confirmado — y queda en los logs por qué."""
    _cliente_falso(monkeypatch, "")
    with caplog.at_level("WARNING"):
        assert asyncio.run(openai_engine.clasificar_confirmacion("confirmá esos 3")) == "other"
    assert "no devolvió veredicto" in caplog.text


# ── La escalada del camino de texto ────────────────────────────────────

def _sin_red(monkeypatch, modelos: tuple[str, str, str], efforts: tuple[str, str]) -> list[str]:
    """Reemplaza la llamada al modelo por un registro de a quién se le preguntó."""
    llamados: list[str] = []

    async def _extraer(model, effort, messages):
        llamados.append(model)
        return contrato.IntentResult(intent="DESCONOCIDO")

    monkeypatch.setattr(openai_engine, "_extraer_con_modelo", _extraer)
    monkeypatch.setattr(openai_engine, "_modelos", lambda: modelos)
    monkeypatch.setattr(
        openai_engine,
        "get_settings",
        lambda: SimpleNamespace(openai_effort_capaz=efforts[0], openai_effort_texto=efforts[1]),
    )
    return llamados


def test_no_escala_al_mismo_modelo(monkeypatch, caplog) -> None:
    """Igualar los dos modelos en Railway alcanza para caer acá:
    escalar ahí es hacer esperar al operador una segunda vez para preguntarle lo
    mismo al mismo modelo."""
    llamados = _sin_red(monkeypatch, ("gpt-5", "gpt-5", "gpt-5-mini"), ("low", "low"))
    with caplog.at_level("WARNING"):
        asyncio.run(openai_engine.extraer_intencion("cobré 100 lucas", None, []))
    assert llamados == ["gpt-5"]
    assert "No se escala" in caplog.text


def test_escala_cuando_el_capaz_es_otro_modelo(monkeypatch) -> None:
    llamados = _sin_red(monkeypatch, ("gpt-5", "gpt-5-mini", "gpt-5-mini"), ("medium", "low"))
    asyncio.run(openai_engine.extraer_intencion("cobré 100 lucas", None, []))
    assert llamados == ["gpt-5-mini", "gpt-5"]


def test_escala_si_cambia_el_esfuerzo_aunque_sea_el_mismo_modelo(monkeypatch) -> None:
    """Mismo modelo con más razonamiento sí es un segundo intento distinto."""
    llamados = _sin_red(monkeypatch, ("gpt-5", "gpt-5", "gpt-5-mini"), ("high", "low"))
    asyncio.run(openai_engine.extraer_intencion("cobré 100 lucas", None, []))
    assert llamados == ["gpt-5", "gpt-5"]


# ── Los cuatro veredictos ──────────────────────────────────────────────

def test_confirm_plus_no_se_lee_como_confirm() -> None:
    """"confirm_plus" CONTIENE "confirm": buscar el corto primero se lo comería
    siempre, y el pedido extra del operador se perdería en silencio."""
    assert contrato.interpretar_veredicto("confirm_plus") == "confirm_plus"
    assert contrato.interpretar_veredicto("confirm") == "confirm"


def test_un_veredicto_que_no_se_entiende_cae_en_other() -> None:
    """Ante la duda, el mensaje se procesa como uno nuevo. Lo contrario —darlo
    por confirmado— carga una operación que el operador no confirmó."""
    for basura in ("", "   ", "no sé", "sí?", None):
        assert contrato.interpretar_veredicto(basura) == "other"


def test_los_dos_motores_interpretan_el_veredicto_igual() -> None:
    """Si cada motor lo leyera a su manera, el mismo "dale" haría cosas
    distintas según qué proveedor esté atendiendo."""
    for modulo in (claude, openai_engine):
        assert modulo.interpretar_veredicto is contrato.interpretar_veredicto


def test_el_prompt_del_clasificador_ensena_los_cuatro_veredictos() -> None:
    """El catálogo del prompt y el que sabe interpretar el código son el mismo:
    una categoría que el prompt enseña y el código no reconoce cae en "other"
    sin que falle nada."""
    for veredicto in contrato.VEREDICTOS:
        assert f'"{veredicto}"' in contrato._CONFIRM_CLASSIFIER_PROMPT, veredicto


def test_el_prompt_prohibe_confirmar_una_correccion() -> None:
    """Confirmar algo que el operador estaba corrigiendo carga plata mal; el
    camino inverso solo le hace repetir el pedido."""
    prompt = contrato._CONFIRM_CLASSIFIER_PROMPT.lower()
    assert "corrige" in prompt and "nunca" in prompt


def test_el_default_es_barato_primero_y_capaz_despues(monkeypatch) -> None:
    """El régimen que pidió el dueño (2026-08-21) vive en los defaults, no en
    una env var suelta: un deploy sin variables ya rutea como corresponde.

    Texto arranca en el modelo chico y escala al capaz solo si se rinde. Si los
    dos volvieran a ser iguales no fallaría nada — el bot se saltea la escalada
    y sigue andando —, solo que el segundo intento dejaría de existir sin que
    nadie se entere."""
    from app.core.config import Settings

    # Aislado del entorno a propósito: se custodia el DEFAULT del código, no lo
    # que tenga cargado la máquina donde corre el test.
    for var in ("OPENAI_MODEL_TEXTO", "OPENAI_MODEL_CAPAZ"):
        monkeypatch.delenv(var, raising=False)
    s = Settings(_env_file=None)
    assert s.openai_model_texto == "gpt-5-mini"
    assert s.openai_model_capaz == "gpt-5"
    assert s.openai_model_texto != s.openai_model_capaz, "sin dos modelos distintos no hay escalada"
