from __future__ import annotations

import base64
import json
import logging
from typing import Any

from anthropic import AsyncAnthropic

from app.core.config import get_settings

# El prompt y la forma del resultado viven en `contrato`, que es agnóstico del
# proveedor. Se re-exportan acá porque medio sistema (y los tests) los importan
# desde este módulo desde antes de que hubiera un segundo motor.
from app.services.ia.contrato import (  # noqa: F401  (re-exportados a propósito)
    INTENTS,
    IntentResult,
    _CONFIRM_CLASSIFIER_PROMPT,
    _SYSTEM_PROMPT,
    _VALID_IMAGE_MIME_TYPES,
    _parse_json_object,
    interpretar_veredicto,
    mensaje_clasificacion,
    contexto_fecha,
)

logger = logging.getLogger(__name__)

# Cliente singleton — se inicializa una sola vez para reutilizar el connection pool
_anthropic_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic_client


# El bot tiene dos cargas de trabajo muy distintas y se rutean por separado según
# venga o no una foto. La señal está disponible ANTES de llamar (`image_bytes`).
#
# OCR de cheques (mensajes con foto): la parte cara de equivocarse. Un dígito mal
# leído es plata mal cargada, y desde que se leen VARIOS cheques por foto la
# exigencia subió. Va con el modelo de mayor capacidad y NO se abarata: un error
# de OCR no lanza excepción ni da señal — devuelve un JSON impecable con el
# número equivocado, así que ninguna escalada lo puede rescatar.
_MODEL_OCR = "claude-opus-5"
_EFFORT_OCR = "medium"

# Interpretación de texto (el grueso del volumen: cobros, gastos, ventas,
# consultas). Es clasificación de intent más extracción de un puñado de campos.
# Acá los errores SÍ se ven —el bot muestra la operación y el operador la
# corrige— y además hay escalada automática, así que el modelo más barato es una
# apuesta acotada. Hasta el commit 0acab9f (2026-08-06) este camino corría en
# Sonnet 4.6 sin razonamiento; Sonnet 5 con effort bajo lo mejora y sale menos.
_MODEL_TEXTO = "claude-sonnet-5"
_EFFORT_TEXTO = "low"

# Clasificar un "dale" / "no" es trivial: va con el modelo más barato y rápido.
# (Su prompt son ~300 tokens y Haiku exige 4.096 para cachear: no se cachea.)
_MODEL_CONFIRMACION = "claude-haiku-4-5"


def _texto_de(response: Any) -> str:
    """Devuelve el texto de la respuesta, salteando los bloques de razonamiento.

    Con el razonamiento activo, `content[0]` puede ser un bloque `thinking` y no
    el texto — leerlo por índice devolvía basura o rompía."""
    for bloque in response.content:
        if getattr(bloque, "type", None) == "text":
            return bloque.text.strip()
    return ""


def _loguear_uso_cache(response: Any, model: str) -> None:
    """Registra si el system prompt se leyó del caché o se volvió a escribir.

    Un caché que no pega no falla: simplemente se cobra todo a precio lleno, en
    silencio. Este log es la única forma de notarlo. `leidos` en 0 mensaje tras
    mensaje significa que algo está rompiendo el prefijo (o que los mensajes
    llegan tan espaciados que el caché vence entre uno y otro).
    """
    try:
        uso = response.usage
        logger.info(
            "Claude uso [%s] — cache escrito: %s, cache leido: %s, entrada sin cachear: %s, salida: %s",
            model,
            getattr(uso, "cache_creation_input_tokens", 0),
            getattr(uso, "cache_read_input_tokens", 0),
            uso.input_tokens,
            uso.output_tokens,
        )
    except Exception:  # el log jamás debe tumbar una operación del bot
        logger.debug("No se pudo leer el uso de tokens de la respuesta.", exc_info=True)



_TOPE_CONFIRMACION = 16


async def _pedir_veredicto(contenido: str, tope: int) -> tuple[str, Any]:
    """Una pasada del clasificador. Devuelve (veredicto, respuesta cruda)."""
    response = await _get_client().messages.create(
        model=_MODEL_CONFIRMACION,
        max_tokens=tope,
        system=_CONFIRM_CLASSIFIER_PROMPT,
        messages=[{"role": "user", "content": contenido}],
    )
    return interpretar_veredicto(_texto_de(response)), response


async def clasificar_confirmacion(text: str, operacion_pendiente: str = "") -> str:
    """Decide qué hizo el operador con el pedido de confirmación.

    Recibe **también la operación pendiente** —lo que el bot le preguntó—, porque
    sin eso el clasificador juzga a ciegas: "3,5" puede ser una corrección del
    porcentaje que está en pantalla o un dato de otra cosa, y la frase sola no
    alcanza para saberlo.

    **Un veredicto vacío no es un veredicto, es una falla**: se reintenta con más
    tope y, si vuelve a pasar, se avisa por Telegram. Haiku no razona, así que
    acá el tope alcanza de sobra — pero el camino de recuperación es el mismo en
    los dos motores, para que cambiar de proveedor no cambie qué pasa cuando algo
    sale mal.

    Returns:
        'confirm', 'confirm_plus', 'reject' u 'other'. Ante cualquier falla,
        'other': el mensaje se procesa como uno nuevo en vez de darse por
        confirmado — nunca se ejecuta una operación que no se confirmó.
    """
    text = (text or "").strip()
    if not text:
        return "other"

    contenido = mensaje_clasificacion(operacion_pendiente, text)
    try:
        veredicto, _ = await _pedir_veredicto(contenido, _TOPE_CONFIRMACION)
        if veredicto:
            return veredicto

        logger.warning(
            "El clasificador (%s) no devolvió veredicto, reintentando con más tope.",
            _MODEL_CONFIRMACION,
        )
        veredicto, respuesta = await _pedir_veredicto(contenido, _TOPE_CONFIRMACION * 4)
        if veredicto:
            return veredicto

        await _alertar_sin_veredicto(getattr(respuesta, "usage", None))
        return "other"
    except Exception as exc:
        logger.error("Error clasificando confirmación con Claude: %s", exc)
        return "other"


async def _alertar_sin_veredicto(uso: Any) -> None:
    """Avisa por Telegram que el clasificador se quedó mudo dos veces seguidas.

    No rompe nada visible —el bot contesta— pero le cancela operaciones al
    operador sin dejar rastro. El import va adentro para no atar el motor de IA
    al monitor: es una dependencia de aviso, no de funcionamiento.
    """
    logger.error(
        "El clasificador (%s) no devolvió veredicto ni con el tope ampliado.", _MODEL_CONFIRMACION
    )
    try:
        from app.services import monitor

        await monitor.alertar_error(
            clave="clasificador-sin-veredicto",
            titulo="El clasificador de confirmaciones no contesta",
            detalle=(
                f"Modelo: {_MODEL_CONFIRMACION}\nUso: {uso}\n\n"
                "Dos intentos sin veredicto. El bot está procesando esas respuestas "
                "como mensajes nuevos, así que NO ejecuta lo pendiente: el operador "
                "tiene que volver a confirmar. Revisar tope y modelo de confirmación."
            ),
        )
    except Exception:  # una alerta que falla no puede tumbar una operación
        logger.debug("No se pudo alertar por el clasificador mudo.", exc_info=True)


# ---------------------------------------------------------------------------
# Cliente Claude
# ---------------------------------------------------------------------------
async def _extraer_con_modelo(
    model: str,
    effort: str,
    messages: list[dict[str, Any]],
) -> IntentResult | None:
    """Una pasada de extracción contra un modelo concreto.

    Devuelve None cuando la llamada falla de forma DURA: JSON ilegible, rechazo
    de los clasificadores de seguridad, o error de red. Esas son las únicas
    señales confiables de que el modelo no pudo, y son las que habilitan a
    reintentar con uno más capaz. Un resultado con datos equivocados pero bien
    formado es indistinguible de uno correcto y sale por el camino normal.
    """
    client = _get_client()
    try:
        response = await client.messages.create(
            model=model,
            # Tope de thinking + respuesta JUNTOS. El razonamiento viene activo
            # por defecto en estos modelos, así que un cap chico (el viejo era
            # 1024) se consume razonando y trunca el JSON a medio escribir.
            # Es un techo, no un cargo: solo se paga lo que se genera.
            max_tokens=8192,
            output_config={"effort": effort},
            # El system prompt son ~32.000 caracteres idénticos en cada mensaje: es el
            # bloque más caro y el más estable, así que se cachea. Una lectura
            # cacheada cuesta ~10% de la entrada normal. El caché es un match de
            # PREFIJO — si algún día se interpola algo variable acá (fecha, nombre
            # del operador), deja de haber hits y no avisa: hay que mirar los
            # contadores que se loguean abajo.
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )

        _loguear_uso_cache(response, model)

        if response.stop_reason == "refusal":
            logger.warning("Claude (%s) rechazó el mensaje por sus clasificadores.", model)
            return None

        parsed = _parse_json_object(_texto_de(response))

        # Validar que el intent sea uno de los reconocidos
        if parsed.get("intent") not in INTENTS:
            parsed["intent"] = "DESCONOCIDO"

        return IntentResult(**parsed)

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Error parseando respuesta de Claude (%s): %s", model, exc)
        return None
    except Exception as exc:
        logger.error("Error llamando a Claude (%s): %s", model, exc)
        return None


async def extraer_intencion(
    text: str,
    image_bytes: bytes | None,
    history: list[dict[str, Any]],
    media_mime_type: str = "image/jpeg",
) -> IntentResult:
    """Llama a Claude con el mensaje actual + historial y devuelve la intención extraída.

    Args:
        text: Texto del mensaje (o transcripción de audio).
        image_bytes: Bytes de la imagen (foto de cheque), o None.
        history: Historial previo de la sesión (lista de mensajes Claude).

    Returns:
        IntentResult con intent, data estructurada y respuesta para el operador.
    """
    # Construir el contenido del mensaje actual
    if image_bytes:
        b64 = base64.standard_b64encode(image_bytes).decode()
        base_mime = media_mime_type.split(";")[0].strip()
        if base_mime not in _VALID_IMAGE_MIME_TYPES:
            base_mime = "image/jpeg"
        user_content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": base_mime,
                    "data": b64,
                },
            },
            {
                "type": "text",
                "text": (
                    f"{contexto_fecha()} El operador envió una foto de cheque."
                    + (f" Su mensaje adicional: {text}" if text else "")
                ),
            },
        ]
    else:
        user_content = [
            {"type": "text", "text": f"{contexto_fecha()} {text or '(mensaje vacío)'}"}
        ]

    # Construir la lista de mensajes con historial + mensaje actual
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_content}]

    _NO_INTERPRETADO = IntentResult(
        intent="DESCONOCIDO",
        respuesta_usuario="⚠️ No pude interpretar el mensaje. ¿Podés repetirlo con más detalle?",
    )

    # ── Camino OCR: foto de cheque(s) ────────────────────────────────────────
    # Sin escalada. Ya es el modelo tope, y no hay a qué escalar.
    if image_bytes is not None:
        return await _extraer_con_modelo(_MODEL_OCR, _EFFORT_OCR, messages) or _NO_INTERPRETADO

    # ── Camino texto: primero el modelo barato ───────────────────────────────
    resultado = await _extraer_con_modelo(_MODEL_TEXTO, _EFFORT_TEXTO, messages)

    # Se escala solo ante falla dura (None) o ante un DESCONOCIDO, que en un bot
    # donde el operador únicamente manda operaciones equivale a "me rindo".
    # NO se escala en ACLARACION_REQUERIDA: pedir un dato que el operador
    # realmente no dijo es la respuesta correcta, no una falla del modelo.
    if resultado is not None and resultado.intent != "DESCONOCIDO":
        return resultado

    logger.info(
        "Escalando a %s (el camino de texto devolvió %s)",
        _MODEL_OCR,
        "una falla dura" if resultado is None else "DESCONOCIDO",
    )
    escalado = await _extraer_con_modelo(_MODEL_OCR, _EFFORT_OCR, messages)

    return escalado or resultado or _NO_INTERPRETADO

