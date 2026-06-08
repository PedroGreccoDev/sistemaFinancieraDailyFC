from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    """Representación normalizada de un mensaje entrante de WhatsApp."""

    phone: str                          # Número sin sufijo @c.us
    message_type: str                   # "text" | "audio" | "image"
    text: str = ""                      # Texto o caption
    media_bytes: bytes | None = None    # Se descarga aparte vía media_url
    media_mime_type: str = ""           # MIME type del media
    media_url: str = ""                 # URL del media en el file server de WAHA
    message_id: str = ""


def parse_webhook(body: dict[str, Any]) -> IncomingMessage | None:
    """Parsea el payload de WAHA y devuelve un IncomingMessage normalizado.

    Retorna None si el evento no es un mensaje entrante procesable.
    """
    # Solo procesar eventos de nuevos mensajes entrantes
    if body.get("event") != "message":
        return None

    payload: dict[str, Any] = body.get("payload", {})

    # Ignorar mensajes propios (enviados por el bot)
    if payload.get("fromMe", True):
        return None

    remote_jid: str = payload.get("from", "")

    # Ignorar grupos (@g.us) y broadcasts
    if "@g.us" in remote_jid or "broadcast" in remote_jid:
        return None

    # Extraer número limpio (solo dígitos)
    phone = remote_jid.split("@")[0]
    if not phone.isdigit():
        return None

    message_id: str = payload.get("id", "")
    body_text: str = (payload.get("body") or "").strip()

    # ── Media (imagen / audio) ────────────────────────────────────────────────
    # WAHA marca hasMedia y adjunta media.{url,mimetype}; el archivo se baja aparte.
    if payload.get("hasMedia"):
        media: dict[str, Any] = payload.get("media") or {}
        media_url: str = media.get("url", "")
        mime_type: str = media.get("mimetype", "")

        if not media_url:
            logger.warning("Mensaje con hasMedia pero sin media.url (mime=%s)", mime_type)
            return None

        if mime_type.startswith("audio"):
            return IncomingMessage(
                phone=phone,
                message_type="audio",
                media_mime_type=mime_type,
                media_url=media_url,
                message_id=message_id,
            )

        if mime_type.startswith("image"):
            return IncomingMessage(
                phone=phone,
                message_type="image",
                text=body_text,  # caption
                media_mime_type=mime_type,
                media_url=media_url,
                message_id=message_id,
            )

        logger.debug("Tipo de media no manejado: %s", mime_type)
        return None

    # ── Texto plano ────────────────────────────────────────────────────────────
    if body_text:
        return IncomingMessage(
            phone=phone,
            message_type="text",
            text=body_text,
            message_id=message_id,
        )

    return None
