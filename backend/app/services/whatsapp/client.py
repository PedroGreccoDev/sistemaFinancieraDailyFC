from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)


def _graph_base() -> str:
    settings = get_settings()
    return f"https://graph.facebook.com/{settings.whatsapp_api_version}"


def _auth_headers() -> dict[str, str]:
    settings = get_settings()
    return {"Authorization": f"Bearer {settings.whatsapp_access_token}"}


async def send_text(phone: str, text: str) -> None:
    """Envía un mensaje de texto al operador vía WhatsApp Cloud API.

    Args:
        phone: Número de teléfono en formato internacional, solo dígitos
            (ej. 5491123456789).
        text: Texto a enviar (soporta *negrita* y saltos de línea).

    Nota: la Cloud API solo permite mensajes de texto libre dentro de la
    ventana de 24h posterior al último mensaje del usuario. Fuera de esa
    ventana hay que usar plantillas aprobadas; el envío fallaría con un
    error 131047 que queda registrado en el log.
    """
    settings = get_settings()
    url = f"{_graph_base()}/{settings.whatsapp_phone_number_id}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": phone,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_auth_headers())
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Error enviando mensaje WA a %s: %s — %s",
            phone,
            exc,
            exc.response.text,
        )
    except httpx.HTTPError as exc:
        logger.error("Error enviando mensaje WA a %s: %s", phone, exc)


async def send_template(
    phone: str,
    template_name: str,
    params: list[str],
    lang: str = "es_AR",
) -> bool:
    """Envía un mensaje de PLANTILLA aprobada (notificaciones proactivas).

    A diferencia de send_text, una plantilla se puede enviar sin que el
    operador haya escrito en las últimas 24h. La plantilla debe estar
    creada y aprobada en el panel de Meta, y `lang` debe coincidir
    exactamente con el código de idioma con el que se aprobó.

    Args:
        phone: Número destino en formato internacional (solo dígitos).
        template_name: Nombre de la plantilla aprobada en Meta.
        params: Valores para los placeholders {{1}}, {{2}}, ... del cuerpo,
            en orden.
        lang: Código de idioma de la plantilla (ej. "es_AR", "es").

    Returns:
        True si Meta aceptó el envío, False si falló.
    """
    settings = get_settings()
    url = f"{_graph_base()}/{settings.whatsapp_phone_number_id}/messages"
    payload: dict[str, Any] = {
        "messaging_product": "whatsapp",
        "to": phone,
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": lang},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }
            ],
        },
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(url, json=payload, headers=_auth_headers())
            response.raise_for_status()
        return True
    except httpx.HTTPStatusError as exc:
        logger.error(
            "Error enviando plantilla '%s' a %s: %s — %s",
            template_name,
            phone,
            exc,
            exc.response.text,
        )
        return False
    except httpx.HTTPError as exc:
        logger.error("Error enviando plantilla '%s' a %s: %s", template_name, phone, exc)
        return False


async def get_media_bytes(media_id: str) -> tuple[bytes, str]:
    """Descarga media (audio/imagen) desde la WhatsApp Cloud API.

    Es un proceso de dos pasos:
      1. GET /{media_id} → devuelve una URL temporal de descarga.
      2. GET sobre esa URL (con el Bearer token) → devuelve los bytes.

    Args:
        media_id: El ID del media incluido en el mensaje entrante.

    Returns:
        Tuple (bytes del archivo, mime_type).
    """
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        # Paso 1: resolver la URL de descarga.
        meta_resp = await client.get(
            f"{_graph_base()}/{media_id}", headers=_auth_headers()
        )
        meta_resp.raise_for_status()
        meta = meta_resp.json()
        media_url: str = meta["url"]
        mime_type: str = meta.get("mime_type", "application/octet-stream")

        # Paso 2: descargar los bytes (requiere el mismo Bearer token).
        media_resp = await client.get(media_url, headers=_auth_headers())
        media_resp.raise_for_status()

    return media_resp.content, mime_type
