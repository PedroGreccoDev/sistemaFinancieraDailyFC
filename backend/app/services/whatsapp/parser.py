from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    """Representación normalizada de un mensaje entrante de WhatsApp."""

    phone: str                          # Número en formato internacional (solo dígitos)
    message_type: str                   # "text" | "audio" | "image"
    text: str = ""                      # Texto o caption
    media_bytes: bytes | None = None    # Se descarga aparte vía client.get_media_bytes
    media_mime_type: str = ""           # MIME type del media
    media_id: str = ""                  # ID del media en la Cloud API (para descargarlo)
    message_id: str = ""


def parse_webhook(body: dict[str, Any]) -> IncomingMessage | None:
    """Parsea el payload de la WhatsApp Cloud API y devuelve un IncomingMessage.

    Retorna None si el evento no es un mensaje entrante procesable
    (por ejemplo, los webhooks de estado: enviado/entregado/leído).

    Estructura del payload:
        entry[].changes[].value.messages[]
    """
    if body.get("object") != "whatsapp_business_account":
        return None

    try:
        change = body["entry"][0]["changes"][0]
        value: dict[str, Any] = change["value"]
    except (KeyError, IndexError, TypeError):
        return None

    # Los webhooks de estado (statuses) no traen "messages": ignorarlos.
    messages = value.get("messages")
    if not messages:
        return None

    message: dict[str, Any] = messages[0]
    phone: str = message.get("from", "")
    if not phone.isdigit():
        return None

    message_id: str = message.get("id", "")
    msg_type: str = message.get("type", "")

    # ── Texto plano ──────────────────────────────────────────────────────────
    if msg_type == "text":
        text = message.get("text", {}).get("body", "")
        return IncomingMessage(
            phone=phone,
            message_type="text",
            text=text.strip(),
            message_id=message_id,
        )

    # ── Audio / nota de voz ──────────────────────────────────────────────────
    if msg_type == "audio":
        audio: dict[str, Any] = message.get("audio", {})
        return IncomingMessage(
            phone=phone,
            message_type="audio",
            media_id=audio.get("id", ""),
            media_mime_type=audio.get("mime_type", "audio/ogg; codecs=opus"),
            message_id=message_id,
        )

    # ── Imagen ───────────────────────────────────────────────────────────────
    if msg_type == "image":
        image: dict[str, Any] = message.get("image", {})
        return IncomingMessage(
            phone=phone,
            message_type="image",
            text=image.get("caption", "").strip(),
            media_id=image.get("id", ""),
            media_mime_type=image.get("mime_type", "image/jpeg"),
            message_id=message_id,
        )

    logger.debug("Tipo de mensaje no manejado: %s", msg_type)
    return None
