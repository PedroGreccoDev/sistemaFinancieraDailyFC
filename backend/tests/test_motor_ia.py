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
