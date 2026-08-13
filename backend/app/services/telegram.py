"""Canal de alertas por Telegram.

Es **el único canal de aviso que no depende de lo que estamos vigilando**: cuando
la sesión de WhatsApp se cae, avisar por WhatsApp es imposible. Por eso las
alertas de salud (§health) van por acá y no por WAHA.

Nunca lanza: una alerta que revienta el proceso que intentaba alertar es peor
que no tener alerta. Todos los fallos se loguean y devuelven `False`.
"""

from __future__ import annotations

import html
import logging

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(10.0)
_API = "https://api.telegram.org"


def destinatarios() -> list[str]:
    """Chat IDs configurados (`TELEGRAM_CHAT_IDS`, separados por coma)."""
    crudo = get_settings().telegram_chat_ids
    return [c.strip() for c in crudo.split(",") if c.strip()]


def configurado() -> bool:
    """Si hay token y al menos un destinatario para poder alertar."""
    return bool(get_settings().telegram_bot_token) and bool(destinatarios())


def escapar(texto: str) -> str:
    """Escapa texto variable para interpolarlo en un mensaje `parse_mode=HTML`."""
    return html.escape(str(texto), quote=False)


async def enviar_alerta(texto: str) -> bool:
    """Manda `texto` (HTML de Telegram) a todos los destinatarios.

    Returns:
        `True` si al menos un destinatario lo recibió; `False` si no hay
        Telegram configurado o si fallaron todos los envíos.
    """
    settings = get_settings()
    token = settings.telegram_bot_token
    chats = destinatarios()

    if not token or not chats:
        logger.warning("Telegram sin configurar (token/chat ids); alerta no enviada: %s", texto)
        return False

    url = f"{_API}/bot{token}/sendMessage"
    enviado = False
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for chat_id in chats:
            payload = {
                "chat_id": chat_id,
                "text": texto,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            }
            try:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                enviado = True
            except httpx.HTTPError as exc:
                logger.error("No se pudo enviar la alerta a Telegram (chat %s): %s", chat_id, exc)

    return enviado
