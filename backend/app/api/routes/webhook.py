from __future__ import annotations

import logging
import re
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services import monitor
# El motor concreto (Claude / OpenAI) lo elige `motor` por env var; acá no
# se sabe ni hace falta cuál está atendiendo (ver services/ia/motor.py).
from app.services.ia import motor as ia_motor
from app.services.ia import whisper as ia_whisper
from app.services.whatsapp import client as wa_client
from app.services.whatsapp import confirmacion as wa_confirmacion
from app.services.whatsapp import dispatcher as wa_dispatcher
from app.services.whatsapp import parser as wa_parser
from app.services.whatsapp import session as wa_session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhook", tags=["webhook"])

# Palabras y modismos (rioplatenses) que el operador usa para confirmar o cancelar.
# Lo que no caiga acá se resuelve con el clasificador de Claude (clasificar_confirmacion).
_CONFIRM_WORDS = frozenset({
    # afirmaciones básicas
    "sí", "si", "ok", "okk", "oka", "okey", "okay", "yes", "yep", "sip", "sipi",
    "s", "ya", "va", "vamos", "vale", "bueno", "buenas",
    # confirmaciones explícitas
    "confirmar", "confirmo", "confirmado", "confirmá", "afirmativo",
    # modismos argentinos
    "dale", "de una", "deuna", "obvio", "obviamente", "tal cual", "talcual",
    "claro", "correcto", "perfecto", "exacto", "listo", "joya", "barbaro",
    "bárbaro", "buenisimo", "buenísimo", "genial", "mandale", "mandalé", "metele",
    "metelé", "sale", "hacelo", "andá", "anda", "y dale", "es asi", "es así",
    "asi es", "así es", "de diez", "de10", "todo bien",
    # emojis
    "👍", "👌", "✅", "🤝",
})
_REJECT_WORDS = frozenset({
    # negaciones básicas
    "no", "nop", "nope", "naa", "nah", "nahh", "n", "negativo", "nones",
    # cancelaciones explícitas
    "cancelar", "cancelá", "cancela", "cancel", "anular", "anulá",
    # modismos argentinos
    "para", "pará", "frená", "frena", "olvidate", "olvidalo", "dejá", "deja",
    "dejalo", "borra", "borralo", "borrá", "mejor no", "no no", "ni ahí",
    "ni ahi", "ni en pedo", "ni a palos", "ni loco", "minga", "no va", "nada",
    # emojis
    "👎", "❌", "🚫",
})


def _ubicacion(exc: BaseException) -> str:
    """`archivo.py:línea` del último frame de la excepción, para ubicar el error.

    Es lo único del traceback que se puede mandar afuera sin riesgo de filtrar
    datos del negocio: nombres de archivo y números de línea, sin valores.
    """
    tb = exc.__traceback__
    if tb is None:
        return "ubicación desconocida"
    ultimo = traceback.extract_tb(tb)[-1]
    return f"{Path(ultimo.filename).name}:{ultimo.lineno}"


def _normalizar_repeticiones(palabra: str) -> str:
    """Colapsa letras repetidas (siii→si) y repeticiones de 'si'/'no' (sisi→si)."""
    # Colapsa cualquier letra repetida a una sola: "siii"/"sii" → "si", "daleee" → "dale".
    # Seguro porque ninguna palabra de confirmación/rechazo tiene letras dobles legítimas.
    palabra = re.sub(r"(.)\1+", r"\1", palabra)
    # Colapsa repeticiones de afirmación/negación pegadas: "sisi"→"si", "nono"→"no"
    m = re.fullmatch(r"(si|no)(?:\1)+", palabra)
    if m:
        return m.group(1)
    return palabra


def _clasificar_respuesta(text: str) -> str | None:
    """Devuelve 'confirm', 'reject' o None si no se puede clasificar."""
    normalized = text.strip().lower().rstrip(".!¡¿? ")
    if not normalized:
        return None

    # Match directo de la frase completa (cubre "tal cual", "mejor no", "no no")
    if normalized in _CONFIRM_WORDS:
        return "confirm"
    if normalized in _REJECT_WORDS:
        return "reject"

    # Tokeniza y normaliza repeticiones para tolerar "sisi", "siii", "dale dale"
    tokens = [_normalizar_repeticiones(t) for t in re.split(r"[\s,]+", normalized) if t]
    if not tokens:
        return None

    es_confirm = all(t in _CONFIRM_WORDS for t in tokens)
    es_reject = all(t in _REJECT_WORDS for t in tokens)
    if es_confirm and not es_reject:
        return "confirm"
    if es_reject and not es_confirm:
        return "reject"
    return None


# Cómo se nombra cada intent cuando hay que decirle al operador qué quedó sin
# cargar. En castellano y en minúscula porque va dentro de una frase.
_NOMBRE_INTENT = {
    "REGISTRAR_CHEQUE": "la carga del cheque",
    "VENDER_CHEQUE": "la venta del cheque",
    "FIAR_CHEQUE": "el fiado del cheque",
    "COBRAR_CHEQUE": "el cobro del cheque",
    "RECHAZAR_CHEQUE": "el rechazo del cheque",
    "NUEVO_PRESTAMO": "el préstamo",
    "COBRAR_CUOTA": "el cobro de la cuota",
    "COBRAR_FIADO_EFECTIVO": "el cobro del fiado",
    "COBRAR_FIADO_CON_CHEQUE": "el cobro del fiado con cheque",
    "COBRAR_DEUDA_CLIENTE": "el cobro al cliente",
    "COMPENSAR_DEUDA": "la compensación",
    "REGISTRAR_DEUDA": "la deuda",
    "REGISTRAR_DEUDA_CLIENTE": "la deuda del cliente",
    "MOVIMIENTO_EFECTIVO": "la operación de dólares",
    "REGISTRAR_GASTO": "el gasto",
    "EDITAR_OPERACION": "la corrección",
    "REVERTIR_OPERACION": "la reversión",
}


def _describir(intent_result: Any) -> str:
    """Nombre corto de una operación pendiente, para avisar que no se cargó.

    Un intent sin entrada en la tabla cae en algo genérico en vez de mostrarle
    al operador el nombre interno en mayúsculas: que aparezca un intent nuevo
    sin dar de alta acá no puede convertir el aviso en jerga de programador.
    """
    return _NOMBRE_INTENT.get(getattr(intent_result, "intent", ""), "la operación anterior")


@router.post("/whatsapp")
async def recibir_mensaje(request: Request, background_tasks: BackgroundTasks) -> JSONResponse:
    """Endpoint que recibe los webhooks de WAHA.

    Responde 200 inmediatamente y procesa en background para que WAHA no reintente
    si Claude demora más del timeout del webhook.
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

    # ── 3. Encolar procesamiento y responder 200 de inmediato ────────────────
    background_tasks.add_task(_procesar_mensaje_safe, msg, settings)
    return JSONResponse(content={"ok": True})


async def _procesar_mensaje_safe(
    msg: wa_parser.IncomingMessage,
    settings: Any,
) -> None:
    """Wrapper con manejo de errores para ejecutar como BackgroundTask."""
    try:
        await _procesar_mensaje(msg, settings)
    except Exception as exc:
        logger.exception("Error no controlado procesando mensaje de %s: %s", msg.phone, exc)
        # El operador ve un "error inesperado" y sigue; sin este aviso nadie del
        # lado técnico se entera de que el bot dejó de poder operar.
        #
        # Va el tipo de error y DÓNDE ocurrió, no el traceback: el mensaje de una
        # excepción de SQLAlchemy arrastra el SQL con sus parámetros (montos,
        # nombres de clientes, teléfonos) y Telegram es un tercero. El detalle
        # completo ya quedó arriba, en el log de Railway, que es donde se debuggea.
        await monitor.alertar_error(
            clave=f"webhook-{type(exc).__name__}",
            titulo="Error procesando un mensaje del bot",
            detalle=f"{type(exc).__name__} en {_ubicacion(exc)}\n\nEl detalle completo está en los logs de Railway.",
        )
        await wa_client.send_text(
            msg.phone,
            "⚠️ Ocurrió un error inesperado. Por favor intentá de nuevo.",
        )


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
    # Si había un intent esperando confirmación, resolver antes de llamar al modelo.
    #
    # La regla de acá es que **un mensaje nunca se tira**. El operador escribe
    # como habla: confirma y de paso pregunta, corrige un dato sobre la marcha, o
    # directamente arranca con la operación siguiente sin contestar la anterior.
    # Antes cualquiera de esas tres cosas cancelaba lo pendiente Y descartaba el
    # mensaje nuevo, así que había que repetir todo — de ahí las ráfagas de la
    # misma operación cargada cinco veces seguidas en los logs.
    aviso_pendiente = ""
    pending = wa_session.get_pending_intent(phone)
    if pending is not None:
        if msg.message_type == "image":
            # Una foto no responde "sí" ni "no": es una operación nueva. Antes el
            # flujo de confirmación solo miraba los mensajes de texto, así que la
            # foto pasaba de largo y lo pendiente QUEDABA VIVO — el operador
            # cargaba el cheque de la foto, decía "dale" pensando en ese, y
            # terminaba confirmando la operación anterior.
            logger.info(
                "%s mandó una foto con algo pendiente (%s) — se descarta lo pendiente",
                phone, pending.intent,
            )
            clasificacion = "other"
        else:
            clasificacion = _clasificar_respuesta(text_content)
            # La lista rápida no reconoció el modismo: que lo interprete el modelo.
            if clasificacion is None:
                logger.info(
                    "Respuesta no literal de %s — consultando al modelo: %r", phone, text_content
                )
                clasificacion = await ia_motor.clasificar_confirmacion(
                    text_content, getattr(pending, "respuesta_usuario", "")
                )

        if clasificacion == "reject":
            logger.info("Operación cancelada por %s", phone)
            wa_session.clear_pending_intent(phone)
            wa_session.clear_session(phone)
            await wa_client.send_text(phone, "✅ Operación cancelada.")
            return

        if clasificacion in ("confirm", "confirm_plus"):
            logger.info(
                "Operación confirmada por %s (intent=%s, veredicto=%s)",
                phone, pending.intent, clasificacion,
            )
            pending_foto = wa_session.get_pending_foto(phone)
            wa_session.clear_pending_intent(phone)
            if clasificacion == "confirm":
                wa_session.add_user_message(phone, text_content)
            await _ejecutar_y_responder(
                phone=phone, intent_result=pending, msg_at=msg.timestamp, foto=pending_foto
            )
            if clasificacion == "confirm":
                return
            # "confirm_plus": confirmó Y pidió algo más ("dale, y decime cuánto
            # queda debiendo"). Lo pendiente ya se ejecutó; el mensaje sigue de
            # largo por el flujo normal para que se atienda lo que falta. El
            # historial conserva la respuesta de la operación, así que el modelo
            # tiene con qué resolver un "y eso cuánto me deja".
            logger.info("Además de confirmar, %s pidió algo más — sigue el flujo normal", phone)
        else:
            # No contestó la pregunta: mandó otra cosa. Lo pendiente NO se carga
            # —nunca se confirmó—, pero el mensaje se procesa igual en vez de
            # tirarse. El aviso viaja pegado a la respuesta para que el operador
            # sepa, en el mismo mensaje, que aquello quedó sin cargar.
            logger.info(
                "%s no respondió a la confirmación (intent pendiente=%s) — se procesa como mensaje nuevo",
                phone, pending.intent,
            )
            wa_session.clear_pending_intent(phone)
            aviso_pendiente = (
                f"⚠️ No confirmaste lo anterior ({_describir(pending)}), así que NO se cargó.\n\n"
            )

    # ── 3d. Historial de sesión ──────────────────────────────────────────────
    history = wa_session.get_history(phone)
    wa_session.add_user_message(phone, text_content or "(imagen de cheque)")

    # ── 3e. Llamar a Claude ──────────────────────────────────────────────────
    image_bytes = msg.media_bytes if msg.message_type == "image" else None
    # Foto a persistir si el cheque se carga por imagen (bytes, mime).
    foto = (
        (image_bytes, msg.media_mime_type or "image/jpeg")
        if image_bytes is not None
        else None
    )
    intent_result = await ia_motor.extraer_intencion(
        text=text_content,
        image_bytes=image_bytes,
        history=history,
        media_mime_type=msg.media_mime_type if msg.message_type == "image" else "image/jpeg",
    )
    logger.info("Intent extraído: %s (phone=%s)", intent_result.intent, phone)

    # El modelo ya decidió si hacía falta confirmar (regla 10 del prompt), pero
    # esa es una instrucción y no una garantía. Acá se revisa el monto de verdad:
    # una operación grande no se ejecuta sin que el operador la vea, aunque el
    # modelo se haya olvidado de preguntar.
    if not intent_result.confirmacion_requerida:
        hace_falta, monto, moneda = wa_confirmacion.exige_confirmacion(
            intent_result,
            settings.confirmacion_umbral_ars,
            settings.confirmacion_umbral_usd,
        )
        if hace_falta:
            logger.warning(
                "Confirmación forzada por monto (%s %s, intent=%s, phone=%s): "
                "el modelo no la había pedido.",
                f"{monto:,.2f}", moneda, intent_result.intent, phone,
            )
            intent_result.confirmacion_requerida = True
            # El modelo escribió el mensaje creyendo que la operación se
            # ejecutaba: describe lo hecho, no lo que va a hacer.
            intent_result.respuesta_usuario = wa_confirmacion.con_pregunta(
                intent_result.respuesta_usuario
            )

    # ── 3f. Dispatch ─────────────────────────────────────────────────────────
    if intent_result.confirmacion_requerida:
        wa_session.set_pending_intent(phone, intent_result)
        wa_session.set_pending_foto(phone, foto)
        wa_session.add_assistant_message(phone, intent_result.respuesta_usuario)
        await wa_client.send_text(phone, aviso_pendiente + intent_result.respuesta_usuario)
        return

    await _ejecutar_y_responder(
        phone=phone,
        intent_result=intent_result,
        msg_at=msg.timestamp,
        foto=foto,
        aviso=aviso_pendiente,
    )


async def _ejecutar_y_responder(
    phone: str,
    intent_result: ia_motor.IntentResult,
    msg_at: datetime | None = None,
    foto: tuple[bytes, str] | None = None,
    aviso: str = "",
) -> None:
    """Ejecuta el dispatch en BD y envía la respuesta al operador.

    `aviso` se antepone a lo que se le manda. Lo usa el flujo de confirmación
    para contar, en el MISMO mensaje, que la operación anterior quedó sin
    cargar: mandarlo aparte obliga al operador a atar dos mensajes seguidos, y
    el que importa —el que dice que algo no se cargó— es el que se pierde de
    vista cuando abajo ya hay otro.
    """
    db = SessionLocal()
    try:
        limpiar_sesion, respuesta = wa_dispatcher.dispatch(
            db, phone, intent_result, msg_at=msg_at, foto=foto
        )
    except wa_dispatcher.ConfirmacionRequerida as exc:
        # Un handler pide confirmar antes de impactar (ej: gasto duplicado).
        # Guardamos el mismo intent como pendiente, marcado para no re-preguntar.
        intent_result.data["_dup_confirmado"] = True
        wa_session.set_pending_intent(phone, intent_result)
        wa_session.set_pending_foto(phone, foto)
        wa_session.add_assistant_message(phone, exc.mensaje)
        await wa_client.send_text(phone, aviso + exc.mensaje)
        return
    finally:
        db.close()

    if limpiar_sesion:
        wa_session.clear_session(phone)
    # Siempre guardar la respuesta real en historial (no solo el respuesta_usuario del
    # modelo). Esto permite que consultas (cartera, cliente) queden visibles para el
    # siguiente turno.
    wa_session.add_assistant_message(phone, respuesta)
    await wa_client.send_text(phone, aviso + respuesta)
