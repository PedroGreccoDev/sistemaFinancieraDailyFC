from __future__ import annotations

import base64
import json
import logging
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Cliente singleton — se inicializa una sola vez para reutilizar el connection pool
_anthropic_client: AsyncAnthropic | None = None


def _get_client() -> AsyncAnthropic:
    global _anthropic_client
    if _anthropic_client is None:
        _anthropic_client = AsyncAnthropic(api_key=get_settings().anthropic_api_key)
    return _anthropic_client


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
    "COBRAR_FIADO_EFECTIVO",
    "COBRAR_FIADO_CON_CHEQUE",
    "REGISTRAR_DEUDA",
    "MOVIMIENTO_EFECTIVO",
    "REGISTRAR_GASTO",
    "CONSULTA_CARTERA",
    "CONSULTA_CLIENTE",
    "CONSULTA_PRESTAMOS",
    "EDITAR_OPERACION",
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
   Cuándo: El operador entrega un cheque a alguien como crédito abierto (sin cuotas fijas).
   Ej: "Se lo fié a Juan al 3%", "Fié el 12345 a María Gómez al 2.5%"
   La deuda queda abierta: el cliente pagará en efectivo o con otro cheque cuando pueda.
   data:
     - nro_cheque: string
     - cliente_nombre: string
     - porcentaje_venta: number (% de descuento pactado; el cliente deberá el monto menos ese %)

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
   Cuándo: Un deudor pagó una o varias cuotas de un préstamo.
   Ej: "Juan pagó", "Cobré cuota de Pedro García", "Pedro pagó la 3",
       "Bono me pagó dos cuotas", "María abonó 3 cuotas"
   data:
     - cliente_nombre: string
     - numero_cuota: integer o null (null = primera pendiente; si paga varias, la primera del lote)
     - cantidad_cuotas: integer (cuántas cuotas pagó; default 1; "dos cuotas" → 2)

8. COBRAR_FIADO_EFECTIVO
   Cuándo: Un cliente con fiado abierto paga parte o todo en efectivo.
   Ej: "Juan me pagó $50000 del fiado", "María saldó el cheque en efectivo"
   data:
     - cliente_nombre: string
     - monto_cobrado: number (monto que está pagando en efectivo)

9. COBRAR_FIADO_CON_CHEQUE
   Cuándo: Un cliente con fiado abierto paga entregando un nuevo cheque.
   Ej: "Juan me trajo un cheque de $100000 al 2% para saldar el fiado"
   El sistema calculará si el cheque cubre toda la deuda o solo una parte.
   data:
     - cliente_nombre: string
     - nro_cheque_pago: string (número del cheque que entrega como pago)
     - monto_cheque: number (valor nominal del cheque)
     - porcentaje_compra_cheque: number (% de compra de ese cheque)
     - fecha_emision: "YYYY-MM-DD" o null
     - fecha_pago: "YYYY-MM-DD" o null

10. REGISTRAR_DEUDA
   Cuándo: El operador informa que el negocio le debe dinero a alguien.
   Ej: "Le debo 5000 a Fernando Cuello", "Anotá que le debo 200 dólares a María por los insumos"
   Si no se menciona el concepto (razón/motivo de la deuda) → ACLARACION_REQUERIDA.
   data:
     - acreedor: string (a quién se le debe)
     - concepto: string (razón o motivo de la deuda; REQUERIDO)
     - monto: number
     - moneda: "ARS" o "USD" (default ARS)
     - fecha_vencimiento: "YYYY-MM-DD" o null (si se menciona una fecha límite)

11. MOVIMIENTO_EFECTIVO
   Cuándo: El operador compró o vendió divisas.
   Ej: "Compré 1000 dólares a 1250", "Vendí 500 USD a 1260, gané 5000"
   ⚠️ REGLA CRÍTICA: la cotización SIEMPRE la dicta el operador. JAMÁS la asumas.
   data:
     - tipo: "compra" o "venta"
     - moneda: "ARS" o "USD" (casi siempre "USD"; usá regla 4 para determinarlo)
     - monto: number (cantidad de divisa)
     - cotizacion_aplicada: number (precio ARS por unidad; ACLARACION_REQUERIDA si no la dice)
     - ganancia: number (0 si no se menciona)
     - cliente_nombre: string o null

12. REGISTRAR_GASTO
    Cuándo: El operador cargó uno o varios gastos operativos del negocio (nafta, comida, parking, insumos, etc.)
    Ej: "Cargué 10.000 de nafta", "Gasté 5000 en almuerzo", "Pagué 3500 de estacionamiento",
        "Gasté milqui en YPF y 12 mil en el kiosco" (DOS gastos en un solo mensaje)
    Si el operador menciona VARIOS gastos en el mismo mensaje, devolvé TODOS en la lista
    "gastos" (uno por ítem). NUNCA pidas elegir cuál cargar primero: cargá todos.
    data:
      - gastos: array de objetos, cada uno con:
          * concepto: string (descripción del gasto, ej: "nafta", "almuerzo")
          * monto: number (en ARS salvo que especifiquen USD)
          * moneda: "ARS" o "USD" (default ARS)
      (Si es un solo gasto, igual usá la lista con un único elemento.)

13. CONSULTA_CARTERA
    Cuándo: El operador pregunta qué cheques tiene.
    Ej: "Qué cheques tengo?", "Estado de cartera", "Cuánto hay en cartera?"
    data: {}

13b. CONSULTA_CLIENTE
    Cuándo: El operador pregunta qué deudas o situación tiene un cliente específico.
    Ej: "Qué tiene Juan?", "No me acuerdo lo que me debe Pedro", "Cuánto me debe María?",
        "Qué deuda tiene X", "Qué tiene pendiente X"
    data:
      - cliente_nombre: string

13c. CONSULTA_PRESTAMOS
    Cuándo: El operador pregunta por los préstamos en general (sin nombrar a un cliente),
        típicamente para saber qué tiene por cobrar.
    Ej: "Qué préstamos tengo por cobrar?", "Qué préstamos tengo activos?",
        "Cuánto me deben en préstamos?", "Listame los préstamos"
    ⚠️ NO confundir con CONSULTA_CARTERA (eso es cheques). Los préstamos son dinero
       prestado sin cheque. Si dice "préstamo(s)" o "cuotas" → CONSULTA_PRESTAMOS.
    data: {}

14. EDITAR_OPERACION
    Cuándo: El operador quiere corregir un dato ya registrado.
    Ej: "El cheque 12345 tiene mal el porcentaje, era 3% no 2%",
        "Corregí el monto del último movimiento, era 1500 USD",
        "El último gasto era $8000 no $5000",
        "La deuda con Fernando tiene mal el monto, son $6000"
    data:
      - tipo_operacion: "CHEQUE" | "MOVIMIENTO" | "GASTO" | "PASIVO"
      - identificador: string
          * CHEQUE → el nro_cheque (puede ser parcial, ej: "681"; el sistema lo resuelve)
          * MOVIMIENTO / GASTO → "ultimo" (el más reciente registrado)
          * PASIVO → "ultimo" o el nombre del acreedor si se menciona
      - campo: string (qué campo corregir)
          * CHEQUE EN_CARTERA: "monto" | "porcentaje_compra" | "fecha_emision" | "fecha_pago" | "cliente_origen"
          * CHEQUE VENDIDO o FIADO: todo lo anterior + "porcentaje_venta" | "cliente_destino"
          * CHEQUE COBRADO o RECHAZADO: igual que EN_CARTERA
          * MOVIMIENTO: "monto" | "cotizacion_aplicada" | "ganancia" | "tipo"
          * GASTO: "concepto" | "monto" | "moneda"
          * PASIVO: "acreedor" | "concepto" | "monto" | "moneda" | "fecha_vencimiento"
      - nuevo_valor: string | number (el valor correcto)
    Reglas:
      - Los cheques se pueden editar en cualquier estado (es una corrección de datos, no un cambio de estado).
        Al corregir monto o % en un cheque VENDIDO, la ganancia se recalcula automáticamente.
        Al corregir monto o % en un cheque FIADO con fiado abierto, el saldo pendiente se recalcula.
      - Solo pasivos PENDIENTE pueden editarse.
      - Si dice "el último", "lo que acabo de cargar", "lo de recién" → identificador = "ultimo".
      - Para fechas: "YYYY-MM-DD". Para montos y %: número puro sin símbolos.
      - Si no queda claro qué operación o qué campo → ACLARACION_REQUERIDA.

15. ACLARACION_REQUERIDA
    Cuándo: Falta información esencial para completar la operación.
    data:
      - pregunta: string (pregunta concreta y puntual al operador)

16. DESCONOCIDO
    Cuándo: El mensaje no corresponde a ninguna operación del sistema.
    data: {}

═══════════════════════════════════════
REGLAS CRÍTICAS
═══════════════════════════════════════

1. JAMÁS asumas cotizaciones de dólar. Si no la dice → ACLARACION_REQUERIDA.
2. JAMÁS inventes montos, porcentajes, fechas o nombres.
3. Si el operador dice "lo", "este cheque", "ese" sin número → buscalo en el historial.
   Si hace una pregunta o comentario sobre la última operación confirmada que aparece en el
   historial (ej: "240 qué?", "de la deuda que hablamos", "eso está bien?") → respondé en
   respuesta_usuario con una aclaración, y usá intent DESCONOCIDO con data: {}.
4. Moneda default: ARS, salvo que digan "dólares", "USD", "verdes", "cables".
5. Fechas → ISO 8601. "15/8/25" → "2025-08-15".
6. Montos → número puro sin símbolos. "$50.000,50" → 50000.50.
   Lunfardo/jerga de plata argentina (interpretar SIEMPRE así):
     - "luca"/"luka" = 1.000 ("dos lucas" = 2000, "luca y media" = 1500).
     - "milqui" = 1.500 (mil quinientos). "dosqui" = 2.500, "tresqui" = 3.500, etc.
     - "gamba" = 100. "ponja"/"papota" no son montos.
     - "palo" = 1.000.000 ("medio palo" = 500.000). "palo verde" = 1.000.000 USD.
     - "mango"/"mangos"/"peso(s)" = unidad ("5 lucas" → 5000).
     - "diez mil"/"10 mil"/"10mil"/"10k" = 10.000. "12 mil" = 12000.
   Ante duda con un modismo de monto, NO inventes: pedí ACLARACION_REQUERIDA.
7. Nombres → normalizar con mayúsculas. "juan perez" → "Juan Perez".
8. Si hay imagen de cheque → extraer nro_cheque, monto, fecha_emision, fecha_pago con OCR.
   El porcentaje_compra NUNCA está en el cheque: debe venir del mensaje verbal del operador.
   Si no lo menciona → ACLARACION_REQUERIDA.
9. Si el cheque tiene CUIT o número de cuenta, ignorarlo (no es parte del modelo).
10. Si el monto supera $500.000 ARS o 500 USD, o la operación es RECHAZAR_CHEQUE,
    pon confirmacion_requerida: true y describí la operación completa en respuesta_usuario.
    FIAR_CHEQUE solo requiere confirmación si el monto nominal del cheque supera $500.000 ARS.
11. Ambigüedad COBRAR_CUOTA vs COBRAR_FIADO_EFECTIVO: si el operador dice "X me pagó" o
    "cobré a X" sin más contexto, elegí COBRAR_CUOTA (más común). Si menciona "fiado",
    "la deuda" o "lo que me debía del cheque" → COBRAR_FIADO_EFECTIVO.
12. Números de cheque abreviados: si el operador menciona solo los últimos dígitos
    (ej: "el 681") y en el historial hay un cheque cuyo nro termina en ese sufijo
    (ej: "03789681"), usá SIEMPRE el número completo del historial como nro_cheque.
    Si hay ambigüedad o no hay historial con ese cheque → ponés el parcial igual y el
    sistema lo resuelve en la BD. Solo usá ACLARACION_REQUERIDA si hay ambigüedad real.
13. Reconstrucción multi-turno: si el mensaje actual parece ser la respuesta a una
    pregunta de aclaración del asistente (ej: el asistente preguntó qué cheque o qué
    dato, y el operador ahora responde con un número, un nombre o un valor), reconstruí
    la operación original del historial y completala con ese dato.
    Ej: historial muestra que el operador quería corregir el porcentaje_compra de un
    cheque pero faltaba identificarlo, y ahora dice "el 5068" o "el que termina en 5068"
    → devolvé EDITAR_OPERACION con los datos originales más identificador="5068".
    NUNCA respondas con DESCONOCIDO ni ACLARACION_REQUERIDA si la operación original
    está clara en el historial y el operador solo está completando el dato faltante.

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


# MIME types que acepta la API de Claude para imágenes
_VALID_IMAGE_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/gif", "image/webp"})

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
            "CONSULTA_CLIENTE",
            "CONSULTA_PRESTAMOS",
            "ACLARACION_REQUERIDA",
            "DESCONOCIDO",
        }


def _parse_json_object(raw_text: str) -> dict[str, Any]:
    """Extrae el objeto JSON de la respuesta de Claude de forma tolerante.

    Claude a veces antepone texto explicativo o envuelve el JSON en un bloque
    de código markdown, sobre todo en conversaciones multi-turno con historial
    cargado. Intenta el parseo directo y, si falla, recorta desde la primera
    llave de apertura hasta la última de cierre.

    Raises:
        json.JSONDecodeError si no se encuentra un objeto JSON válido.
    """
    text = raw_text.strip()

    # Limpiar bloques de código markdown accidentales.
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Fallback: recortar al objeto JSON más externo (Claude antepuso prosa).
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        return json.loads(text[start : end + 1])

    # Re-lanzar el error original para que el caller lo maneje.
    return json.loads(text)


# ---------------------------------------------------------------------------
# Clasificador de confirmación (modismos argentinos)
# ---------------------------------------------------------------------------
_CONFIRM_CLASSIFIER_PROMPT = """
Sos un clasificador. El operador de un sistema financiero argentino respondió a un
pedido de confirmación de una operación (el bot le preguntó "¿Confirmar?").

Tu tarea: decidir si la respuesta es una CONFIRMACIÓN (sí, dale, adelante) o un
RECHAZO (no, cancelar, frená), interpretando jerga y modismos rioplatenses.

Ejemplos de confirmación: "dale", "de una", "obvio", "tal cual", "mandale",
"metele", "joya", "de diez", "y dale", "afirmativo", "sí obvio", "está perfecto",
"sale", "andá", "hacelo", "listo el pollo".
Ejemplos de rechazo: "ni en pedo", "ni a palos", "ni ahí", "olvidate", "dejá",
"frená", "pará", "mejor no", "borralo", "negativo", "minga", "nones", "naa".

Respondé con UNA sola palabra, sin puntuación ni nada más:
- "confirm" si es confirmación.
- "reject" si es rechazo.
- "unclear" si es ambiguo, una pregunta, o no se entiende como sí/no.
""".strip()


async def clasificar_confirmacion(text: str) -> str:
    """Clasifica una respuesta corta del operador a un pedido de confirmación.

    Pensado como fallback cuando la lista rápida local no reconoce el modismo.
    Usa Haiku (barato y veloz) porque es una tarea de clasificación trivial.

    Returns:
        'confirm', 'reject' o 'unclear' (este último también ante cualquier error).
    """
    text = (text or "").strip()
    if not text:
        return "unclear"

    try:
        client = _get_client()
        response = await client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8,
            system=_CONFIRM_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        veredicto = response.content[0].text.strip().lower()
        if "confirm" in veredicto:
            return "confirm"
        if "reject" in veredicto:
            return "reject"
        return "unclear"
    except Exception as exc:
        logger.error("Error clasificando confirmación con Claude: %s", exc)
        return "unclear"


# ---------------------------------------------------------------------------
# Cliente Claude
# ---------------------------------------------------------------------------
async def extraer_intencion(
    text: str,
    image_bytes: bytes | None,
    history: list[dict[str, Any]],
    media_mime_type: str = "image/jpeg",
) -> IntentResult:
    """Llama a Claude con el mensaje actual + historial y devuelve la intención extraída.

    Args:
        text: Texto del mensaje (o transcripción de audio).
        image_bytes: Bytes de la imagen (foto de cheque), o None.
        history: Historial previo de la sesión (lista de mensajes Claude).

    Returns:
        IntentResult con intent, data estructurada y respuesta para el operador.
    """
    client = _get_client()

    # Construir el contenido del mensaje actual
    if image_bytes:
        b64 = base64.standard_b64encode(image_bytes).decode()
        base_mime = media_mime_type.split(";")[0].strip()
        if base_mime not in _VALID_IMAGE_MIME_TYPES:
            base_mime = "image/jpeg"
        user_content: list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": base_mime,
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
            model="claude-sonnet-4-6",
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        )

        raw_text = response.content[0].text.strip()
        parsed = _parse_json_object(raw_text)

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
