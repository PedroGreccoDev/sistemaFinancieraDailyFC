from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


def _base_url() -> str:
    settings = get_settings()
    return settings.waha_api_url.rstrip("/")


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {"X-Api-Key": settings.waha_api_key, "Content-Type": "application/json"}


async def send_text(phone: str, text: str) -> None:
    """Envía un mensaje de texto al operador vía WAHA.

    Args:
        phone: Número de teléfono sin sufijo (solo dígitos).
        text: Texto a enviar (soporta *negrita* y saltos de línea).
    """
    settings = get_settings()
    url = f"{_base_url()}/api/sendText"
    payload: dict[str, Any] = {
        "session": settings.waha_session,
        "chatId": f"{phone}@c.us",
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Error enviando mensaje WA a %s: %s", phone, exc)


async def get_media_bytes(media_url: str) -> tuple[bytes, str]:
    """Descarga media (audio/imagen) desde WAHA.

    WAHA no incluye el archivo en el webhook: entrega una URL (`payload.media.url`)
    apuntando a su propio file server, que se descarga con la misma API key.

    Args:
        media_url: URL del media provista por el webhook de WAHA.

    Returns:
        Tuple (bytes del archivo, mime_type).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(media_url, headers={"X-Api-Key": get_settings().waha_api_key})
        response.raise_for_status()

    mime_type = response.headers.get("content-type", "application/octet-stream")
    return response.content, mime_type
