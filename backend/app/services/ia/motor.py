"""Qué motor de IA interpreta cada mensaje del bot.

Es la única puerta que usa el webhook: pide `extraer_intencion` /
`clasificar_confirmacion` y acá se decide si eso lo atiende Claude
(`claude.py`) o OpenAI (`openai_engine.py`). Los dos implementan el mismo
contrato y comparten el system prompt (`contrato.py`).

**Se elige por camino, no uno para todo** (`IA_PROVIDER_TEXTO` /
`IA_PROVIDER_OCR`), porque son dos trabajos con perfiles de riesgo opuestos:

- **OCR (mensajes con foto).** Un dígito mal leído es plata mal cargada y **no
  da ninguna señal**: el modelo devuelve un JSON impecable con el número
  equivocado. No hay excepción que atrapar ni escalada que lo rescate, y el
  error se descubre el día que no cierra la caja. Cambiar de motor acá se
  prueba solo, mirando cheques cargados contra las fotos.
- **Texto (el grueso del volumen: cobros, gastos, consultas).** Acá el error se
  ve —el bot muestra la operación antes de confirmar— y hay escalada
  automática, así que probar otro motor es una apuesta acotada.

Mezclarlos en una sola variable obligaría a cambiar los dos juntos, y si algo
empeorara no habría forma de saber cuál de los dos fue.

El historial de sesión (`services/whatsapp/session.py`) son turnos de texto
plano, así que cambiar de proveedor a mitad de conversación no la rompe.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.config import get_settings
from app.services.ia import claude as _claude
from app.services.ia import openai_engine as _openai
from app.services.ia.contrato import IntentResult  # noqa: F401  (re-exportado)

logger = logging.getLogger(__name__)

_MOTORES = {"anthropic": _claude, "openai": _openai}
_DEFAULT = "anthropic"


def _resolver(nombre: str) -> Any:
    """Devuelve el módulo del motor pedido.

    Un nombre desconocido **no tumba el bot**: se loguea y se cae al motor por
    defecto. Un typo en una env var de Railway no puede dejar la financiera sin
    poder cargar una operación.
    """
    motor = _MOTORES.get((nombre or "").strip().lower())
    if motor is None:
        logger.warning(
            "Proveedor de IA desconocido: %r. Se usa %s. Válidos: %s",
            nombre,
            _DEFAULT,
            ", ".join(_MOTORES),
        )
        return _MOTORES[_DEFAULT]
    return motor


def motor_texto() -> Any:
    return _resolver(get_settings().ia_provider_texto)


def motor_ocr() -> Any:
    return _resolver(get_settings().ia_provider_ocr)


async def extraer_intencion(
    text: str,
    image_bytes: bytes | None,
    history: list[dict[str, Any]],
    media_mime_type: str = "image/jpeg",
) -> IntentResult:
    """Interpreta el mensaje del operador con el motor que corresponda.

    La señal de ruteo es la misma que usan los motores por dentro para elegir
    modelo: si viene foto, es el camino OCR.
    """
    motor = motor_ocr() if image_bytes is not None else motor_texto()
    return await motor.extraer_intencion(text, image_bytes, history, media_mime_type)


async def clasificar_confirmacion(text: str, operacion_pendiente: str = "") -> str:
    """Clasifica la respuesta a un pedido de confirmación, con el motor de texto.

    Va con el de texto porque es lo que es: interpretar una respuesta escrita.

    `operacion_pendiente` es lo que el bot le preguntó al operador. Sin eso el
    clasificador juzga la frase sola y no la situación: un dato suelto puede ser
    una corrección de lo que está en pantalla o el comienzo de otra operación, y
    esa diferencia decide si se carga plata o no.
    """
    return await motor_texto().clasificar_confirmacion(text, operacion_pendiente)
