from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0)

# Esperas (segundos) antes de cada reintento ante fallos transitorios de red/WAHA.
# Total de intentos = len(_RETRY_WAITS) + 1 (el primero es inmediato).
_RETRY_WAITS = (0.5, 1.0, 2.0)

# Estados de sesión WAHA en los que tiene sentido intentar enviar.
_SESSION_OK = ("WORKING", "STARTING")


def _base_url() -> str:
    settings = get_settings()
    return settings.waha_api_url.rstrip("/")


def _headers() -> dict[str, str]:
    settings = get_settings()
    return {"X-Api-Key": settings.waha_api_key, "Content-Type": "application/json"}


async def _request_retry(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """Hace una request a WAHA reintentando ante fallos transitorios (red/5xx).

    Un `numberExists=false` u otra respuesta 2xx NO es error y vuelve en el primer
    intento; solo se reintenta ante `httpx.HTTPError` (timeouts, conexión, 4xx/5xx).

    Raises:
        httpx.HTTPError: si todos los intentos fallan.
    """
    last_exc: httpx.HTTPError | None = None
    for attempt, wait in enumerate((0.0, *_RETRY_WAITS)):
        if wait:
            await asyncio.sleep(wait)
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                response = await client.request(method, url, **kwargs)
                response.raise_for_status()
                return response
        except httpx.HTTPError as exc:
            last_exc = exc
            logger.warning(
                "WAHA %s %s falló (intento %d/%d): %s",
                method, url, attempt + 1, len(_RETRY_WAITS) + 1, exc,
            )
    assert last_exc is not None
    raise last_exc


async def _ensure_session() -> str:
    """Devuelve el estado de la sesión WAHA, auto-levantándola si quedó `STOPPED`.

    No fuerza `restart` (podría obligar a re-escanear el QR); solo `start`, que
    reanuda una sesión ya autenticada. Si está `SCAN_QR_CODE`/`FAILED` no hay nada
    que automatizar: hace falta intervención humana.

    Raises:
        httpx.HTTPError: si no se puede leer el estado de la sesión.
    """
    settings = get_settings()
    base = f"{_base_url()}/api/sessions/{settings.waha_session}"
    status = (await _request_retry("GET", base, headers=_headers())).json().get("status", "")

    if status == "STOPPED":
        logger.info("Sesión WAHA detenida; intentando iniciarla")
        try:
            await _request_retry("POST", f"{base}/start", headers=_headers())
            await asyncio.sleep(2.0)  # darle tiempo a pasar a WORKING
            status = (await _request_retry("GET", base, headers=_headers())).json().get("status", "")
        except httpx.HTTPError as exc:
            logger.error("No se pudo iniciar la sesión WAHA: %s", exc)

    return status


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
    data = (await _request_retry("GET", url, params=params, headers=_headers())).json()
    if not data.get("numberExists"):
        return None
    return data.get("chatId") or f"{phone}@c.us"


async def send_text(phone: str, text: str) -> bool:
    """Envía un mensaje de texto vía WAHA. Devuelve si se entregó.

    Maximiza la entrega: asegura que la sesión esté operativa, resuelve el `chatId`
    canónico (ver `_resolve_chat_id`) y reintenta ante fallos transitorios. Devuelve
    `False` (sin reventar) cuando de verdad no se puede entregar: número que no está
    en WhatsApp, o sesión esperando QR. Si la verificación falla por red, cae al
    formato directo `{phone}@c.us` para no perder el envío al operador.

    Args:
        phone: Número de teléfono sin sufijo (solo dígitos).
        text: Texto a enviar (soporta *negrita* y saltos de línea).

    Returns:
        `True` si WAHA aceptó el envío; `False` si no se pudo enviar.
    """
    settings = get_settings()

    # 1. Asegurar la sesión (auto-levanta si quedó STOPPED). Si no se puede leer el
    #    estado, asumimos operativa y dejamos que el reintento del envío decida.
    try:
        status = await _ensure_session()
    except httpx.HTTPError as exc:
        logger.warning("No se pudo leer el estado de la sesión WAHA, intento enviar igual: %s", exc)
        status = "WORKING"
    if status not in _SESSION_OK:
        logger.error("Sesión WAHA en estado %r; no se puede enviar a %s (¿escanear QR?)", status, phone)
        return False

    # 2. Resolver el chatId canónico (corrige el dígito 9 de los celulares AR/BR).
    try:
        chat_id = await _resolve_chat_id(phone)
    except httpx.HTTPError as exc:
        logger.warning("No se pudo verificar %s en WhatsApp, uso formato directo: %s", phone, exc)
        chat_id = f"{phone}@c.us"
    if chat_id is None:
        logger.warning("El número %s no está registrado en WhatsApp; no se envía", phone)
        return False

    # 3. Enviar (con reintentos).
    url = f"{_base_url()}/api/sendText"
    payload: dict[str, Any] = {
        "session": settings.waha_session,
        "chatId": chat_id,
        "text": text,
    }
    try:
        await _request_retry("POST", url, json=payload, headers=_headers())
        return True
    except httpx.HTTPError as exc:
        logger.error("Error enviando mensaje WA a %s tras reintentos: %s", phone, exc)
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
