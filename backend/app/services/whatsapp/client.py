from __future__ import annotations

import base64
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


def _base_url() -> str:
    settings = get_settings()
    return settings.evolution_api_url.rstrip("/")


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {"apikey": settings.evolution_api_key, "Content-Type": "application/json"}


async def send_text(phone: str, text: str) -> None:
    """Envía un mensaje de texto al operador vía Evolution API.

    Args:
        phone: Número de teléfono sin @s.whatsapp.net (solo dígitos).
        text: Texto a enviar (soporta *negrita* y saltos de línea).
    """
    settings = get_settings()
    url = f"{_base_url()}/message/sendText/{settings.evolution_instance}"
    payload: dict[str, Any] = {"number": phone, "text": text}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Error enviando mensaje WA a %s: %s", phone, exc)


async def get_media_bytes(message_key: dict[str, Any]) -> tuple[bytes, str]:
    """Descarga media (audio/imagen) desde Evolution API.

    Args:
        message_key: El objeto `key` del webhook de Evolution API.

    Returns:
        Tuple (bytes del archivo, mime_type).
    """
    settings = get_settings()
    url = f"{_base_url()}/chat/getBase64FromMediaMessage/{settings.evolution_instance}"
    payload = {"key": message_key}

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.post(url, json=payload, headers=_headers())
        response.raise_for_status()

    data = response.json()
    raw_b64: str = data.get("base64", "")
    mime_type: str = data.get("mimetype", "application/octet-stream")

    return base64.b64decode(raw_b64), mime_type
