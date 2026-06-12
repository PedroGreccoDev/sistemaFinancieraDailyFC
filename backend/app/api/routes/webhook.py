from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services.ia import claude as ia_claude
from app.services.ia import whisper as ia_whisper
from app.services.whatsapp import client as wa_client
from app.services.whatsapp import dispatcher as wa_dispatcher
from app.services.whatsapp import parser as wa_parser
from app.services.whatsapp import session as wa_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Palabras que el operador usa para confirmar o cancelar una operación pendiente
_CONFIRM_WORDS = frozenset({"sí", "si", "ok", "dale", "confirmar", "confirmo", "yes", "va", "s", "👍"})
_REJECT_WORDS  = frozenset({"no", "cancelar", "cancelá", "cancel", "nop", "nope", "n"})


def _clasificar_respuesta(text: str) -> str | None:
    """Devuelve 'confirm', 'reject' o None si no se puede clasificar."""
    normalized = text.strip().lower().rstrip(".!¡¿?")
    if normalized in _CONFIRM_WORDS:
        return "confirm"
    if normalized in _REJECT_WORDS:
        return "reject"
    return None


@router.post("/whatsapp")
async def recibir_mensaje(request: Request) -> JSONResponse:
    """Endpoint que recibe los webhooks de WAHA.

    Siempre responde 200 rápidamente para que WAHA no reintente.
    El procesamiento ocurre en el mismo hilo pero es tolerante a errores.
    """
    settings = get_settings()

    try:
        body: dict[str, Any] = await request.json()
    except Exception:
        return JSONResponse(content={"ok": True})

    # ── 1. Parsear el payload ────────────────────────────────────────────────
    msg = wa_parser.parse_webhook(body)
    if msg is None:
        return JSONResponse(content={"ok": True})

    # ── 2. Verificar operador autorizado ─────────────────────────────────────
    operator_phone = settings.whatsapp_operator_phone.strip()
    if operator_phone and msg.phone != operator_phone:
        logger.warning("Mensaje de número no autorizado: %s", msg.phone)
        return JSONResponse(content={"ok": True})

    # ── 3. Procesar el mensaje ───────────────────────────────────────────────
    try:
        await _procesar_mensaje(msg, settings)
    except Exception as exc:
        logger.exception("Error no controlado procesando mensaje de %s: %s", msg.phone, exc)
        await wa_client.send_text(
            msg.phone,
            "⚠️ Ocurrió un error inesperado. Por favor intentá de nuevo.",
        )

    return JSONResponse(content={"ok": True})


async def _procesar_mensaje(
    msg: wa_parser.IncomingMessage,
    settings: Any,
) -> None:
    """Pipeline completo: media → transcripción → confirmación/IA → dispatch → respuesta WA."""

    phone = msg.phone

    # ── 3a. Obtener media si hace falta ──────────────────────────────────────
    if msg.message_type in ("audio", "image") and msg.media_bytes is None:
        try:
            msg.media_bytes, msg.media_mime_type = await wa_client.get_media_bytes(
                msg.media_url
            )
        except Exception as exc:
            logger.error("No se pudo descargar media de %s: %s", phone, exc)
            await wa_client.send_text(phone, "⚠️ No pude descargar el archivo. Intentá de nuevo.")
            return

    # ── 3b. Transcribir audio ────────────────────────────────────────────────
    text_content = msg.text
    if msg.message_type == "audio" and msg.media_bytes:
        try:
            text_content = await ia_whisper.transcribir_audio(
                msg.media_bytes, msg.media_mime_type
            )
            logger.info("Audio transcripto (%s chars)", len(text_content))
        except Exception as exc:
            logger.error("Error en Whisper para %s: %s", phone, exc)
            await wa_client.send_text(phone, "⚠️ No pude transcribir el audio. Podés escribirlo.")
            return

    if not text_content and msg.message_type != "image":
        return  # Mensaje vacío sin imagen — ignorar

    # ── 3c. Flujo de confirmación ─────────────────────────────────────────────
    # Si había un intent esperando confirmación, resolver antes de llamar a Claude
    pending = wa_session.get_pending_intent(phone)
    if pending is not None and msg.message_type == "text":
        clasificacion = _clasificar_respuesta(text_content)
        if clasificacion == "confirm":
            logger.info("Operación confirmada por %s (intent=%s)", phone, pending.intent)
            wa_session.clear_pending_intent(phone)
            wa_session.add_user_message(phone, text_content)
            await _ejecutar_y_responder(phone=phone, intent_result=pending, msg_at=msg.timestamp)
            return
        if clasificacion == "reject":
            logger.info("Operación cancelada por %s", phone)
            wa_session.clear_pending_intent(phone)
            wa_session.clear_session(phone)
            await wa_client.send_text(phone, "✅ Operación cancelada.")
            return
        # Respuesta ambigua: cancela el pending y avisa al operador antes de procesar el mensaje
        logger.info("Respuesta ambigua de %s — descartando pending intent", phone)
        wa_session.clear_pending_intent(phone)
        await wa_client.send_text(
            phone,
            "⚠️ No entendí tu respuesta. La operación anterior fue cancelada. Registrala de nuevo si querés.",
        )
        return

    # ── 3d. Historial de sesión ──────────────────────────────────────────────
    history = wa_session.get_history(phone)
    wa_session.add_user_message(phone, text_content or "(imagen de cheque)")

    # ── 3e. Llamar a Claude ──────────────────────────────────────────────────
    image_bytes = msg.media_bytes if msg.message_type == "image" else None
    intent_result = await ia_claude.extraer_intencion(
        text=text_content,
        image_bytes=image_bytes,
        history=history,
        media_mime_type=msg.media_mime_type if msg.message_type == "image" else "image/jpeg",
    )
    logger.info("Intent extraído: %s (phone=%s)", intent_result.intent, phone)

    # ── 3f. Dispatch ─────────────────────────────────────────────────────────
    if intent_result.confirmacion_requerida:
        wa_session.set_pending_intent(phone, intent_result)
        wa_session.add_assistant_message(phone, intent_result.respuesta_usuario)
        await wa_client.send_text(phone, intent_result.respuesta_usuario)
        return

    await _ejecutar_y_responder(phone=phone, intent_result=intent_result, msg_at=msg.timestamp)


async def _ejecutar_y_responder(
    phone: str,
    intent_result: ia_claude.IntentResult,
    msg_at: datetime | None = None,
) -> None:
    """Ejecuta el dispatch en BD y envía la respuesta al operador."""
    db = SessionLocal()
    try:
        limpiar_sesion, respuesta = wa_dispatcher.dispatch(db, phone, intent_result, msg_at=msg_at)
    finally:
        db.close()

    if limpiar_sesion:
        wa_session.clear_session(phone)
    # Siempre guardar la respuesta real en historial (no solo el respuesta_usuario de Claude).
    # Esto permite que consultas (cartera, cliente) queden visibles para el siguiente turno.
    wa_session.add_assistant_message(phone, respuesta)
    await wa_client.send_text(phone, respuesta)
