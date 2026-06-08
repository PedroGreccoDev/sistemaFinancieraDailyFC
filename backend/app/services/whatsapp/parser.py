from __future__ import annotations

import base64
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    """Representación normalizada de un mensaje entrante de WhatsApp."""

    phone: str                          # Número sin @s.whatsapp.net
    message_type: str                   # "text" | "audio" | "image"
    text: str = ""                      # Texto o caption
    media_bytes: bytes | None = None    # Ya decodificado si venía en base64
    media_mime_type: str = ""           # MIME type del media
    message_key: dict[str, Any] = field(default_factory=dict)  # Para descargar media
    message_id: str = ""


def parse_webhook(body: dict[str, Any]) -> IncomingMessage | None:
    """Parsea el payload de Evolution API y devuelve un IncomingMessage normalizado.

    Retorna None si el evento no es un mensaje entrante procesable.
    """
    # Solo procesar eventos de nuevos mensajes
    if body.get("event") != "messages.upsert":
        return None

    data: dict[str, Any] = body.get("data", {})
    key: dict[str, Any] = data.get("key", {})

    # Ignorar mensajes propios (enviados por el bot)
    if key.get("fromMe", True):
        return None

    remote_jid: str = key.get("remoteJid", "")

    # Ignorar grupos (@g.us) y broadcasts
    if "@g.us" in remote_jid or "broadcast" in remote_jid:
        return None

    # Extraer número limpio (solo dígitos)
    phone = remote_jid.split("@")[0]
    if not phone.isdigit():
        return None

    message: dict[str, Any] = data.get("message", {})
    message_type: str = data.get("messageType", "")
    message_id: str = key.get("id", "")

    # ── Texto plano ──────────────────────────────────────────────────────────
    if message_type in ("conversation", "extendedTextMessage"):
        text = message.get("conversation") or message.get(
            "extendedTextMessage", {}
        ).get("text", "")
        return IncomingMessage(
            phone=phone,
            message_type="text",
            text=text.strip(),
            message_key=key,
            message_id=message_id,
        )

    # ── Audio / nota de voz ──────────────────────────────────────────────────
    if message_type in ("audioMessage", "pttMessage"):
        audio_msg: dict[str, Any] = message.get("audioMessage", message.get("pttMessage", {}))
        mime_type: str = audio_msg.get("mimetype", "audio/ogg; codecs=opus")

        media_bytes = _extract_base64(message)
        return IncomingMessage(
            phone=phone,
            message_type="audio",
            media_bytes=media_bytes,
            media_mime_type=mime_type,
            message_key=key,
            message_id=message_id,
        )

    # ── Imagen ───────────────────────────────────────────────────────────────
    if message_type == "imageMessage":
        img_msg: dict[str, Any] = message.get("imageMessage", {})
        caption: str = img_msg.get("caption", "").strip()
        mime_type = img_msg.get("mimetype", "image/jpeg")

        media_bytes = _extract_base64(message)
        return IncomingMessage(
            phone=phone,
            message_type="image",
            text=caption,
            media_bytes=media_bytes,
            media_mime_type=mime_type,
            message_key=key,
            message_id=message_id,
        )

    logger.debug("Tipo de mensaje no manejado: %s", message_type)
    return None


def _extract_base64(message: dict[str, Any]) -> bytes | None:
    """Extrae y decodifica el campo base64 del payload si existe.

    Evolution API incluye este campo cuando WEBHOOK_BASE64=true está configurado.
    """
    raw: str | None = message.get("base64")
    if not raw:
        return None
    try:
        return base64.b64decode(raw)
    except Exception:
        return None
