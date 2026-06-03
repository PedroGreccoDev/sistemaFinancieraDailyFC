from __future__ import annotations

import base64
import json
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Intenciones reconocidas
# ---------------------------------------------------------------------------
INTENTS = {
    "REGISTRAR_CHEQUE",
    "VENDER_CHEQUE",
    "FIAR_CHEQUE",
    "COBRAR_CHEQUE",
    "RECHAZAR_CHEQUE",
    "NUEVO_PRESTAMO",
    "COBRAR_CUOTA",
    "MOVIMIENTO_EFECTIVO",
    "CONSULTA_CARTERA",
    "ACLARACION_REQUERIDA",
    "DESCONOCIDO",
}

# ---------------------------------------------------------------------------
# Prompt del sistema
# ---------------------------------------------------------------------------
_SYSTEM_PROMPT = """
Sos el asistente operativo de un sistema de gestión de cartera financiera privada en Argentina.
Tu ÚNICO interlocutor es el operador autorizado.

TU TAREA: Analizar el mensaje del operador y devolver ÚNICAMENTE un objeto JSON válido.
NUNCA respondas con texto libre. NUNCA uses markdown ni bloques de código. SOLO JSON puro.

═══════════════════════════════════════
OPERACIONES DISPONIBLES
═══════════════════════════════════════

1. REGISTRAR_CHEQUE
   Cuándo: El operador manda foto de cheque o dicta datos de uno nuevo.
   data:
     - nro_cheque: string (número del cheque, sin espacios ni guiones)
     - monto: number ("$50.000,50" → 50000.50)
     - porcentaje_compra: number (% que pagó para comprarlo)
     - fecha_emision: "YYYY-MM-DD" o null
     - fecha_pago: "YYYY-MM-DD" o null
     - cliente_nombre: string o null (de quién lo recibió)

2. VENDER_CHEQUE
   Cuándo: El operador dice que vendió un cheque.
   Ej: "Vendí el 12345 al 3%", "Lo vendí al 2.5% a Juan"
   data:
     - nro_cheque: string
     - porcentaje_venta: number
     - cliente_nombre: string o null (a quién se vendió)

3. FIAR_CHEQUE
   Cuándo: El operador usa el cheque para fiar/prestar a alguien.
   Ej: "Se lo fié a Juan Pérez en 4 cuotas semanales de $5000"
   data:
     - nro_cheque: string
     - cliente_nombre: string
     - credito: number (monto del crédito, usualmente el monto del cheque)
     - moneda: "ARS" o "USD"
     - cuotas: integer
     - frecuencia: "diaria" | "semanal" | "quincenal" | "mensual" | "anual"
     - total_a_cobrar: number (suma que va a cobrar en total)

4. COBRAR_CHEQUE
   Cuándo: El cheque se cobró en ventanilla al vencimiento.
   Ej: "Cobré el cheque 12345", "Pasé el 12345 por ventanilla"
   data:
     - nro_cheque: string

5. RECHAZAR_CHEQUE
   Cuándo: El cheque rebotó o fue rechazado por el banco.
   Ej: "Rebotó el 12345", "Me rechazaron el cheque"
   data:
     - nro_cheque: string

6. NUEVO_PRESTAMO
   Cuándo: El operador prestó dinero directamente (sin cheque).
   Ej: "Presté $50000 a María García en 6 cuotas mensuales de $10000"
   data:
     - cliente_nombre: string
     - credito: number
     - moneda: "ARS" o "USD"
     - cuotas: integer
     - frecuencia: "diaria" | "semanal" | "quincenal" | "mensual" | "anual"
     - total_a_cobrar: number

7. COBRAR_CUOTA
   Cuándo: Un deudor pagó una cuota.
   Ej: "Juan pagó", "Cobré cuota de Pedro García", "Pedro pagó la 3"
   data:
     - cliente_nombre: string
     - numero_cuota: integer o null (null = primera pendiente)

8. MOVIMIENTO_EFECTIVO
   Cuándo: El operador compró o vendió divisas.
   Ej: "Compré 1000 dólares a 1250", "Vendí 500 USD a 1260, gané 5000"
   ⚠️ REGLA CRÍTICA: la cotización SIEMPRE la dicta el operador. JAMÁS la asumas.
   data:
     - tipo: "compra" o "venta"
     - moneda: "USD"
     - monto: number (cantidad de divisa)
     - cotizacion_aplicada: number (precio ARS por unidad)
     - ganancia: number (0 si no se menciona)
     - cliente_nombre: string o null

9. CONSULTA_CARTERA
   Cuándo: El operador pregunta qué cheques tiene.
   Ej: "Qué cheques tengo?", "Estado de cartera", "Cuánto hay en cartera?"
   data: {}

10. ACLARACION_REQUERIDA
    Cuándo: Falta información esencial para completar la operación.
    data:
      - pregunta: string (pregunta concreta y puntual al operador)

11. DESCONOCIDO
    Cuándo: El mensaje no corresponde a ninguna operación del sistema.
    data: {}

═══════════════════════════════════════
REGLAS CRÍTICAS
═══════════════════════════════════════

1. JAMÁS asumas cotizaciones de dólar. Si no la dice → ACLARACION_REQUERIDA.
2. JAMÁS inventes montos, porcentajes, fechas o nombres.
3. Si el operador dice "lo", "este cheque", "ese" sin número → buscalo en el historial.
4. Moneda default: ARS, salvo que digan "dólares", "USD", "verdes", "cables".
5. Fechas → ISO 8601. "15/8/25" → "2025-08-15".
6. Montos → número puro sin símbolos. "$50.000,50" → 50000.50.
7. Nombres → normalizar con mayúsculas. "juan perez" → "Juan Perez".
8. Si hay imagen de cheque → extraer nro_cheque, monto, fecha_emision, fecha_pago con OCR.
9. Si el cheque tiene CUIT o número de cuenta, ignorarlo (no es parte del modelo).
10. Si una operación mueve un monto grande y podría tener consecuencias irreversibles →
    pon confirmacion_requerida: true y describe qué va a hacer en respuesta_usuario.

═══════════════════════════════════════
FORMATO DE RESPUESTA — SIEMPRE ESTE EXACTO
═══════════════════════════════════════

{
  "intent": "NOMBRE_DEL_INTENT",
  "data": { ... },
  "confirmacion_requerida": false,
  "respuesta_usuario": "Texto natural en español para enviar al operador por WhatsApp"
}
""".strip()


# ---------------------------------------------------------------------------
# Resultado de la extracción
# ---------------------------------------------------------------------------
class IntentResult(BaseModel):
    intent: str = Field(default="DESCONOCIDO")
    data: dict[str, Any] = Field(default_factory=dict)
    confirmacion_requerida: bool = False
    respuesta_usuario: str = ""

    def is_write_operation(self) -> bool:
        """True si la intención modifica la base de datos."""
        return self.intent not in {
            "CONSULTA_CARTERA",
            "ACLARACION_REQUERIDA",
            "DESCONOCIDO",
        }


# ---------------------------------------------------------------------------
# Cliente Claude
# ---------------------------------------------------------------------------
async def extraer_intencion(
    text: str,
    image_bytes: bytes | None,
    history: list[dict[str, Any]],
) -> IntentResult:
    """Llama a Claude con el mensaje actual + historial y devuelve la intención extraída.

    Args:
        text: Texto del mensaje (o transcripción de audio).
        image_bytes: Bytes de la imagen (foto de cheque), o None.
        history: Historial previo de la sesión (lista de mensajes Claude).

    Returns:
        IntentResult con intent, data estructurada y respuesta para el operador.
    """
    settings = get_settings()
    client = AsyncAnthropic(api_key=settings.anthropic_api_key)

    # Construir el contenido del mensaje actual
    if image_bytes:
        b64 = base64.standard_b64encode(image_bytes).decode()
        user_content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": b64,
                },
            },
            {
                "type": "text",
                "text": (
                    f"El operador envió una foto de cheque."
                    + (f" Su mensaje adicional: {text}" if text else "")
                ),
            },
        ]
    else:
        user_content = [{"type": "text", "text": text or "(mensaje vacío)"}]

    # Construir la lista de mensajes con historial + mensaje actual
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_content}]

    try:
        response = await client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )

        raw_text = response.content[0].text.strip()

        # Limpiar posibles bloques de código (defensa ante markdown accidental)
        if raw_text.startswith("```"):
            raw_text = raw_text.split("```")[1]
            if raw_text.startswith("json"):
                raw_text = raw_text[4:]
            raw_text = raw_text.strip()

        parsed = json.loads(raw_text)

        # Validar que el intent sea uno de los reconocidos
        if parsed.get("intent") not in INTENTS:
            parsed["intent"] = "DESCONOCIDO"

        return IntentResult(**parsed)

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Error parseando respuesta de Claude: %s", exc)
        return IntentResult(
            intent="DESCONOCIDO",
            respuesta_usuario="⚠️ No pude interpretar el mensaje. ¿Podés repetirlo con más detalle?",
        )
    except Exception as exc:
        logger.error("Error llamando a Claude: %s", exc)
        return IntentResult(
            intent="DESCONOCIDO",
            respuesta_usuario="⚠️ Error interno del sistema de IA. Intentá de nuevo.",
        )
