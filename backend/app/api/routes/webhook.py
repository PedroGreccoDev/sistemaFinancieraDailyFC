from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.session import get_db
from app.services.ia import claude as ia_claude
from app.services.ia import whisper as ia_whisper
from app.services.whatsapp import client as wa_client
from app.services.whatsapp import dispatcher as wa_dispatcher
from app.services.whatsapp import parser as wa_parser
from app.services.whatsapp import session as wa_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])


@router.post("/whatsapp")
async def recibir_mensaje(request: Request) -> JSONResponse:
    """Endpoint que recibe los webhooks de Evolution API.

    Siempre responde 200 rápidamente para que Evolution API no reintente.
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
    """Pipeline completo: media → transcripción → IA → dispatch → respuesta WA."""

    phone = msg.phone

    # ── 3a. Obtener media si hace falta ──────────────────────────────────────
    if msg.message_type in ("audio", "image") and msg.media_bytes is None:
        # WEBHOOK_BASE64 no está activo: descargamos vía API
        try:
            msg.media_bytes, msg.media_mime_type = await wa_client.get_media_bytes(
                msg.message_key
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

    # ── 3c. Historial de sesión ──────────────────────────────────────────────
    history = wa_session.get_history(phone)
    wa_session.add_user_message(phone, text_content or "(imagen de cheque)")

    # ── 3d. Llamar a Claude ──────────────────────────────────────────────────
    image_bytes = msg.media_bytes if msg.message_type == "image" else None
    intent_result = await ia_claude.extraer_intencion(
        text=text_content,
        image_bytes=image_bytes,
        history=history,
    )
    logger.info("Intent extraído: %s (phone=%s)", intent_result.intent, phone)

    # ── 3e. Agregar respuesta de Claude al historial ─────────────────────────
    wa_session.add_assistant_message(phone, intent_result.respuesta_usuario)

    # ── 3f. Dispatch: ejecutar en BD ─────────────────────────────────────────
    # Si requiere confirmación del operador, solo enviamos la pregunta
    if intent_result.confirmacion_requerida:
        await wa_client.send_text(phone, intent_result.respuesta_usuario)
        return

    db = next(get_db())
    try:
        limpiar_sesion, respuesta = wa_dispatcher.dispatch(db, phone, intent_result)
    finally:
        db.close()

    # ── 3g. Limpiar sesión post-transacción ──────────────────────────────────
    if limpiar_sesion:
        wa_session.clear_session(phone)

    # ── 3h. Enviar respuesta al operador ─────────────────────────────────────
    await wa_client.send_text(phone, respuesta)
