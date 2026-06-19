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


async def _resolve_chat_id(phone: str) -> str | None:
    """Resuelve el `chatId` canónico de un número vía WAHA.

    WAHA recomienda llamar a `check-exists` **antes de mandarle a un número nuevo**:
    para AR/BR el JID real puede no coincidir con `{phone}@c.us` por el dígito `9`
    de los celulares, y WAHA aceptaría el envío (201) sin entregarlo. El operador no
    sufre esto porque su `chatId` ya viene canónico desde los mensajes entrantes.

    Returns:
        El `chatId` canónico si el número está en WhatsApp; `None` si no lo está.

    Raises:
        httpx.HTTPError: si la verificación en sí falla (red/WAHA caído).
    """
    settings = get_settings()
    url = f"{_base_url()}/api/contacts/check-exists"
    params = {"phone": phone, "session": settings.waha_session}
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(url, params=params, headers=_headers())
        response.raise_for_status()
    data = response.json()
    if not data.get("numberExists"):
        return None
    return data.get("chatId") or f"{phone}@c.us"


async def send_text(phone: str, text: str) -> bool:
    """Envía un mensaje de texto vía WAHA. Devuelve si se entregó.

    Resuelve primero el `chatId` canónico (ver `_resolve_chat_id`). Si el número no
    está en WhatsApp, no envía y devuelve `False`. Si la verificación falla por red,
    cae al formato directo `{phone}@c.us` para no perder el envío al operador.

    Args:
        phone: Número de teléfono sin sufijo (solo dígitos).
        text: Texto a enviar (soporta *negrita* y saltos de línea).

    Returns:
        `True` si WAHA aceptó el envío; `False` si no se pudo enviar.
    """
    settings = get_settings()

    try:
        chat_id = await _resolve_chat_id(phone)
    except httpx.HTTPError as exc:
        logger.warning("No se pudo verificar %s en WhatsApp, uso formato directo: %s", phone, exc)
        chat_id = f"{phone}@c.us"

    if chat_id is None:
        logger.warning("El número %s no está registrado en WhatsApp; no se envía", phone)
        return False

    url = f"{_base_url()}/api/sendText"
    payload: dict[str, Any] = {
        "session": settings.waha_session,
        "chatId": chat_id,
        "text": text,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_headers())
            response.raise_for_status()
        return True
    except httpx.HTTPError as exc:
        logger.error("Error enviando mensaje WA a %s: %s", phone, exc)
        return False


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
