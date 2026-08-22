"""Motor de IA sobre OpenAI — la otra implementación del contrato del bot.

Hace exactamente lo mismo que `claude.py` (interpretar el mensaje del operador y
devolver un `IntentResult`) contra la API de OpenAI, con **el mismo system
prompt**: el prompt vive en `contrato.py` y los dos motores lo importan de ahí,
así una corrección de reglas de negocio no puede quedar aplicada en un motor y
no en el otro.

Cuál se usa lo decide `motor.py` por env var, por camino (texto / OCR).

Tres diferencias con la API de Anthropic que hay que respetar al tocar esto:

- **El caché del prompt es automático.** OpenAI cachea solo por prefijo, sin
  `cache_control`, a partir de ~1.024 tokens; el system son ~9.000 y va primero,
  así que pega solo. La contracara es la misma que en Claude: interpolar algo
  variable ahí adentro (la fecha, el nombre del operador) lo rompe **en
  silencio**. Por eso la fecha sigue viajando en el mensaje (`contexto_fecha`).
- **`max_completion_tokens`, no `max_tokens`.** Los modelos con razonamiento
  rechazan `max_tokens`, y el tope cubre razonamiento + respuesta juntos: un cap
  chico se consume razonando y trunca el JSON a medio escribir.
- **El JSON se pide por `response_format`.** El modo `json_object` garantiza que
  la respuesta parsee, cosa que en Claude había que arreglar recortando prosa.
  Igual se parsea con el mismo `_parse_json_object` tolerante: si algún día se
  configura un modelo que no soporta el modo, el fallback sigue estando.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any

from openai import AsyncOpenAI

from app.core.config import get_settings
from app.services.ia.contrato import (
    INTENTS,
    IntentResult,
    _CONFIRM_CLASSIFIER_PROMPT,
    _SYSTEM_PROMPT,
    _VALID_IMAGE_MIME_TYPES,
    _parse_json_object,
    interpretar_veredicto,
    contexto_fecha,
)

logger = logging.getLogger(__name__)

# Tope del clasificador de confirmaciones. Cubre razonamiento + respuesta: el
# veredicto es una palabra, pero lo que se paga acá es el margen para que el
# modelo llegue a escribirla. Un cap ajustado al veredicto vuelve vacío y eso
# le cancela la operación al operador (ver `clasificar_confirmacion`).
_TOPE_CONFIRMACION = 512

# Cliente singleton — se inicializa una sola vez para reutilizar el connection pool
_openai_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=get_settings().openai_api_key)
    return _openai_client


def _modelos() -> tuple[str, str, str]:
    """(modelo capaz, modelo texto, modelo confirmación) desde la config.

    Van por env var y no hardcodeados como en `claude.py` a propósito: esto es
    un motor en evaluación, y probar otro modelo tiene que ser cambiar una
    variable en Railway, no un deploy.
    """
    s = get_settings()
    return s.openai_model_capaz, s.openai_model_texto, s.openai_model_confirmacion


def _loguear_uso_cache(response: Any, model: str) -> None:
    """Registra cuánto de la entrada se leyó del caché.

    Un caché que no pega no falla: se cobra todo a precio lleno, en silencio.
    Este log es la única forma de notarlo — `cache leido` en 0 mensaje tras
    mensaje significa que algo está rompiendo el prefijo del system prompt.
    """
    try:
        uso = response.usage
        detalle = getattr(uso, "prompt_tokens_details", None)
        logger.info(
            "OpenAI uso [%s] — cache leido: %s, entrada total: %s, salida: %s, razonamiento: %s",
            model,
            getattr(detalle, "cached_tokens", 0) if detalle else 0,
            uso.prompt_tokens,
            uso.completion_tokens,
            getattr(getattr(uso, "completion_tokens_details", None), "reasoning_tokens", 0),
        )
    except Exception:  # el log jamás debe tumbar una operación del bot
        logger.debug("No se pudo leer el uso de tokens de la respuesta.", exc_info=True)


def _texto_de(response: Any) -> str:
    """Devuelve el texto de la respuesta, o vacío si el modelo no produjo ninguno.

    Un modelo con razonamiento que agota `max_completion_tokens` razonando
    devuelve `content` vacío (o None) sin lanzar: hay que tratarlo como falla
    dura, no dejar que reviente al llamar `.strip()` sobre None.
    """
    try:
        return (response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError):
        return ""


def _contenido_usuario(
    text: str,
    image_bytes: bytes | None,
    media_mime_type: str,
) -> list[dict[str, Any]]:
    """Arma el contenido del mensaje en el formato de OpenAI.

    Es la única parte del armado que difiere de Anthropic: la imagen va como un
    `image_url` con data URI en vez de un bloque `source`/base64.
    """
    if image_bytes is None:
        return [{"type": "text", "text": f"{contexto_fecha()} {text or '(mensaje vacío)'}"}]

    b64 = base64.standard_b64encode(image_bytes).decode()
    base_mime = media_mime_type.split(";")[0].strip()
    if base_mime not in _VALID_IMAGE_MIME_TYPES:
        base_mime = "image/jpeg"
    return [
        {"type": "image_url", "image_url": {"url": f"data:{base_mime};base64,{b64}"}},
        {
            "type": "text",
            "text": (
                f"{contexto_fecha()} El operador envió una foto de cheque."
                + (f" Su mensaje adicional: {text}" if text else "")
            ),
        },
    ]


async def _extraer_con_modelo(
    model: str,
    effort: str,
    messages: list[dict[str, Any]],
) -> IntentResult | None:
    """Una pasada de extracción contra un modelo concreto.

    Devuelve None cuando la llamada falla de forma DURA: JSON ilegible, rechazo
    de los clasificadores de seguridad, respuesta vacía o error de red. Esas son
    las únicas señales confiables de que el modelo no pudo, y son las que
    habilitan a reintentar con uno más capaz. Un resultado con datos
    equivocados pero bien formado es indistinguible de uno correcto y sale por
    el camino normal.
    """
    client = _get_client()
    try:
        kwargs: dict[str, Any] = {
            "model": model,
            # Tope de razonamiento + respuesta JUNTOS. Es un techo, no un cargo:
            # solo se paga lo que se genera.
            "max_completion_tokens": 8192,
            "response_format": {"type": "json_object"},
            # El system va primero y sin nada variable adentro: es lo que hace
            # que el caché de prefijo pegue (ver el docstring del módulo).
            "messages": [{"role": "system", "content": _SYSTEM_PROMPT}, *messages],
        }
        # Vacío = no mandar el parámetro. Un modelo sin razonamiento rechaza
        # `reasoning_effort`, y así se puede probar uno sin tocar código.
        if effort:
            kwargs["reasoning_effort"] = effort

        response = await client.chat.completions.create(**kwargs)

        _loguear_uso_cache(response, model)

        choice = response.choices[0]
        if getattr(choice.message, "refusal", None):
            logger.warning("OpenAI (%s) rechazó el mensaje por sus clasificadores.", model)
            return None
        if choice.finish_reason == "length":
            # Se quedó sin tope: el JSON viene cortado. Es falla dura, no un
            # resultado a medias que haya que intentar parsear.
            logger.warning("OpenAI (%s) truncó la respuesta por max_completion_tokens.", model)
            return None

        crudo = _texto_de(response)
        if not crudo:
            logger.warning("OpenAI (%s) devolvió una respuesta vacía.", model)
            return None

        parsed = _parse_json_object(crudo)

        # Validar que el intent sea uno de los reconocidos
        if parsed.get("intent") not in INTENTS:
            parsed["intent"] = "DESCONOCIDO"

        return IntentResult(**parsed)

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Error parseando respuesta de OpenAI (%s): %s", model, exc)
        return None
    except Exception as exc:
        logger.error("Error llamando a OpenAI (%s): %s", model, exc)
        return None


async def clasificar_confirmacion(text: str) -> str:
    """Clasifica la respuesta del operador a un pedido de confirmación.

    Fallback para cuando la lista rápida local no reconoce el modismo. Va con el
    modelo más barato: decidir si "dale" es un sí es una tarea trivial.

    **El tope tiene que darle lugar al razonamiento, no al veredicto.** La
    respuesta es una palabra, pero `max_completion_tokens` cubre razonamiento +
    respuesta juntos: un modelo que razona se come un cap chico pensando y
    devuelve `content` vacío, sin error. Con el cap en 16 el clasificador
    contestaba "no entendí" a todo lo que no estuviera en la lista rápida, y
    cada confirmación con palabras propias ("confirmá esos 3") le cancelaba la
    operación al operador.

    Devuelve uno de `contrato.VEREDICTOS`, interpretado por la función
    compartida: los dos motores tienen que leer el veredicto igual.

    Returns:
        'confirm', 'confirm_plus', 'reject' u 'other' (este último también ante
        cualquier error: ante la duda, el mensaje se procesa como uno nuevo en
        vez de darse por confirmado).
    """
    text = (text or "").strip()
    if not text:
        return "other"

    _, _, modelo = _modelos()
    try:
        client = _get_client()
        kwargs: dict[str, Any] = {
            "model": modelo,
            "max_completion_tokens": _TOPE_CONFIRMACION,
            "messages": [
                {"role": "system", "content": _CONFIRM_CLASSIFIER_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        # Vacío = no mandar el parámetro, igual que en la extracción: un modelo
        # sin razonamiento rechaza `reasoning_effort`.
        effort = get_settings().openai_effort_confirmacion
        if effort:
            kwargs["reasoning_effort"] = effort

        response = await client.chat.completions.create(**kwargs)

        veredicto = _texto_de(response)
        if not veredicto:
            # Sin este log la falla es invisible: el operador ve su operación
            # cancelada y en los logs no queda nada que lo explique.
            logger.warning(
                "El clasificador (%s) no devolvió veredicto. Uso: %s",
                modelo,
                getattr(response, "usage", None),
            )
            return "other"
        return interpretar_veredicto(veredicto)
    except Exception as exc:
        logger.error("Error clasificando confirmación con OpenAI: %s", exc)
        return "other"


async def extraer_intencion(
    text: str,
    image_bytes: bytes | None,
    history: list[dict[str, Any]],
    media_mime_type: str = "image/jpeg",
) -> IntentResult:
    """Llama a OpenAI con el mensaje actual + historial y devuelve la intención.

    Mismo ruteo que el motor de Claude: el camino OCR (hay foto) va directo al
    modelo más capaz y sin escalada —un error de OCR no da señal a la que
    reaccionar—, y el camino de texto arranca barato y escala solo ante falla
    dura o `DESCONOCIDO`.
    """
    settings = get_settings()
    modelo_capaz, modelo_texto, _ = _modelos()

    user_content = _contenido_usuario(text, image_bytes, media_mime_type)
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_content}]

    _NO_INTERPRETADO = IntentResult(
        intent="DESCONOCIDO",
        respuesta_usuario="⚠️ No pude interpretar el mensaje. ¿Podés repetirlo con más detalle?",
    )

    # ── Camino OCR: foto de cheque(s) — va al modelo capaz, sin escalada ─────
    if image_bytes is not None:
        resultado = await _extraer_con_modelo(
            modelo_capaz, settings.openai_effort_capaz, messages
        )
        return resultado or _NO_INTERPRETADO

    # ── Camino texto: primero el modelo barato ───────────────────────────────
    resultado = await _extraer_con_modelo(
        modelo_texto, settings.openai_effort_texto, messages
    )

    # Se escala solo ante falla dura (None) o ante un DESCONOCIDO, que en un bot
    # donde el operador únicamente manda operaciones equivale a "me rindo".
    # NO se escala en ACLARACION_REQUERIDA: pedir un dato que el operador
    # realmente no dijo es la respuesta correcta, no una falla del modelo.
    if resultado is not None and resultado.intent != "DESCONOCIDO":
        return resultado

    # Escalar al mismo modelo con el mismo esfuerzo es pagar otra espera para
    # volver a preguntarle lo mismo a quien ya se rindió, con el operador
    # mirando el "escribiendo...". Con los defaults de hoy no pasa (texto es
    # `gpt-5-mini` y el capaz es `gpt-5`), pero alcanza con igualar dos env vars
    # en Railway para volver a caer acá, y desde afuera se ve como "el bot se
    # puso lento" y nada más.
    if modelo_capaz == modelo_texto and settings.openai_effort_capaz == settings.openai_effort_texto:
        logger.warning(
            "No se escala: el modelo de texto y el capaz son el mismo (%s, esfuerzo %r). "
            "Poné OPENAI_MODEL_TEXTO con uno más barato para que la escalada sirva.",
            modelo_texto,
            settings.openai_effort_texto,
        )
        return resultado or _NO_INTERPRETADO

    logger.info(
        "Escalando a %s (el camino de texto devolvió %s)",
        modelo_capaz,
        "una falla dura" if resultado is None else "DESCONOCIDO",
    )
    escalado = await _extraer_con_modelo(modelo_capaz, settings.openai_effort_capaz, messages)

    return escalado or resultado or _NO_INTERPRETADO
