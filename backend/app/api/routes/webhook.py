from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse, Response

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


def _normalizar_telefono(phone: str) -> str:
    """Normaliza un número argentino para comparar de forma robusta.

    Meta (Cloud API) suele entregar el `from` de los celulares argentinos SIN
    el 9 intermedio (54 11... en vez de 54 9 11...), mientras que el operador
    casi siempre se configura CON el 9. Sacamos ese 9 de ambos lados para que
    `549 11 ...` y `54 11 ...` se consideren el mismo número.
    """
    digits = "".join(c for c in phone if c.isdigit())
    if digits.startswith("549"):
        return "54" + digits[3:]
    return digits


def _clasificar_respuesta(text: str) -> str | None:
    """Devuelve 'confirm', 'reject' o None si no se puede clasificar."""
    normalized = text.strip().lower().rstrip(".!¡¿?")
    if normalized in _CONFIRM_WORDS:
        return "confirm"
    if normalized in _REJECT_WORDS:
        return "reject"
    return None


@router.get("/whatsapp")
async def verificar_webhook(request: Request) -> Response:
    """Verificación inicial del webhook (Meta envía un GET con un challenge).

    Meta llama a este endpoint una vez al configurar el webhook. Hay que
    devolver el `hub.challenge` en texto plano si el `hub.verify_token`
    coincide con el configurado.
    """
    settings = get_settings()
    params = request.query_params

    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge", "")

    if mode == "subscribe" and token and token == settings.whatsapp_verify_token:
        return PlainTextResponse(content=challenge)

    logger.warning("Verificación de webhook fallida (token inválido)")
    return PlainTextResponse(content="Forbidden", status_code=403)


def _firma_valida(raw_body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valida la firma HMAC-SHA256 que Meta envía en X-Hub-Signature-256."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    received = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


@router.post("/whatsapp")
async def recibir_mensaje(request: Request) -> JSONResponse:
    """Endpoint que recibe los webhooks de la WhatsApp Cloud API.

    Siempre responde 200 rápidamente para que Meta no reintente.
    El procesamiento ocurre en el mismo hilo pero es tolerante a errores.
    """
    settings = get_settings()

    raw_body = await request.body()

    # Validación de firma (solo si hay app_secret configurado).
    if settings.whatsapp_app_secret:
        signature = request.headers.get("X-Hub-Signature-256")
        if not _firma_valida(raw_body, signature, settings.whatsapp_app_secret):
            logger.warning("Webhook con firma inválida — descartado")
            return JSONResponse(content={"ok": True})

    try:
        body: dict[str, Any] = json.loads(raw_body)
    except Exception:
        return JSONResponse(content={"ok": True})

    # ── 1. Parsear el payload ────────────────────────────────────────────────
    msg = wa_parser.parse_webhook(body)
    if msg is None:
        return JSONResponse(content={"ok": True})

    # ── 2. Verificar operador autorizado ─────────────────────────────────────
    operator_phone = settings.whatsapp_operator_phone.strip()
    if operator_phone and _normalizar_telefono(msg.phone) != _normalizar_telefono(operator_phone):
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
    if msg.message_type in ("audio", "image") and msg.media_bytes is None and msg.media_id:
        try:
            msg.media_bytes, msg.media_mime_type = await wa_client.get_media_bytes(
                msg.media_id
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
            await _ejecutar_y_responder(phone=phone, intent_result=pending)
            return
        if clasificacion == "reject":
            logger.info("Operación cancelada por %s", phone)
            wa_session.clear_pending_intent(phone)
            wa_session.clear_session(phone)
            await wa_client.send_text(phone, "✅ Operación cancelada.")
            return
        # Respuesta ambigua: descarta el pending y procesa como mensaje nuevo
        logger.info("Respuesta ambigua de %s — descartando pending intent", phone)
        wa_session.clear_pending_intent(phone)

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

    # ── 3f. Agregar respuesta de Claude al historial ─────────────────────────
    wa_session.add_assistant_message(phone, intent_result.respuesta_usuario)

    # ── 3g. Dispatch ─────────────────────────────────────────────────────────
    if intent_result.confirmacion_requerida:
        wa_session.set_pending_intent(phone, intent_result)
        await wa_client.send_text(phone, intent_result.respuesta_usuario)
        return

    await _ejecutar_y_responder(phone=phone, intent_result=intent_result)


async def _ejecutar_y_responder(
    phone: str,
    intent_result: ia_claude.IntentResult,
) -> None:
    """Ejecuta el dispatch en BD y envía la respuesta al operador."""
    db = SessionLocal()
    try:
        limpiar_sesion, respuesta = wa_dispatcher.dispatch(db, phone, intent_result)
    finally:
        db.close()

    if limpiar_sesion:
        wa_session.clear_session(phone)

    await wa_client.send_text(phone, respuesta)
