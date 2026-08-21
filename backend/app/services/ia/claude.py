from __future__ import annotations

import base64
import json
import logging
from datetime import date
from typing import Any

from anthropic import AsyncAnthropic
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.core.fechas import hoy_local

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
    "COBRAR_DEUDA_CLIENTE",
    "COMPENSAR_DEUDA",
    "REGISTRAR_DEUDA",
    "REGISTRAR_DEUDA_CLIENTE",
    "MOVIMIENTO_EFECTIVO",
    "REGISTRAR_GASTO",
    "CONSULTA",
    # Los tres intents de consulta del contrato anterior. Ya no se documentan en
    # el prompt (los reemplazó CONSULTA con `tipo`), pero siguen en la lista
    # blanca: una sesión abierta arrastra historial con ellos y bajarlos a
    # DESCONOCIDO haría que el bot conteste "no entendí" a media conversación.
    "CONSULTA_CARTERA",
    "CONSULTA_CLIENTE",
    "CONSULTA_PRESTAMOS",
    "EDITAR_OPERACION",
    "REVERTIR_OPERACION",
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
   Cuándo: El operador manda foto(s) de cheque o dicta datos de cheques nuevos.
   ⚠️ UNA FOTO PUEDE TRAER VARIOS CHEQUES. Miralas COMPLETAS y extraé TODOS los que
      veas, aunque estén apilados, superpuestos, en abanico o girados. NUNCA
      devuelvas solo uno si hay más: cada cheque que se te escape es plata que el
      operador cree cargada y no está.
   data:
     - cheques: ARRAY con un objeto por cheque (aunque sea uno solo). Cada objeto:
         * nro_cheque: string (número del cheque, sin espacios ni guiones)
         * banco: string o null (nombre del banco emisor; leerlo del cheque o del
           mensaje. Es CLAVE: el número de cheque solo es único dentro de un banco.)
         * monto: number ("$50.000,50" → 50000.50)
         * porcentaje_compra: number o null (% que pagó para comprarlo)
         * fecha_emision: "YYYY-MM-DD" o null
         * fecha_pago: "YYYY-MM-DD" o null
         * cliente_nombre: string o null (de quién lo recibió)
         * monto_abonado: number o null (SOLO si el operador dice que no lo pagó
           o que lo pagó en parte; null = lo pagó entero, que es lo normal)
   COMPRAR SIN PAGAR: el negocio compra cheques a crédito. Si el operador dice que
   NO lo pagó ("no se lo pagué", "quedé debiendo", "se lo debo", "me lo dio y le
   pago después") → monto_abonado: 0. Si pagó una parte ("le di 200 mil de los
   900") → monto_abonado con esa parte. Si NO dice nada de esto, monto_abonado va
   null: la compra normal es pagada, y asumir lo contrario dejaría una deuda
   inventada con el cliente.
     - Lo que se debe es el VALOR NETO, no el nominal: un cheque de $1.000.000 al
       10% se compra por $900.000, así que a deber son $900.000.
     - A deber hace falta saber A QUIÉN: si no menciona de quién es el cheque →
       ACLARACION_REQUERIDA preguntando a quién se le queda debiendo.
   Reglas del multi-cheque:
     - El porcentaje NUNCA está impreso en el cheque: viene del mensaje del operador.
     - Si dice UN porcentaje y hay VARIOS cheques, aplicá ese mismo a todos
       ("son 4 al 8%" → los 4 con porcentaje_compra 8).
     - Si dice VARIOS porcentajes, asignalos en el orden en que los nombra.
     - Si hay más de un cheque y NO aclara el/los porcentaje(s) → ACLARACION_REQUERIDA
       preguntando si todos llevan el mismo descuento o cuál va con cada uno.
       Nombrá los cheques por su número para que pueda contestarte.
     - Si detectás varios cheques, poné confirmacion_requerida: true y listalos en
       respuesta_usuario (número, banco y monto de cada uno) para que los revise
       antes de cargarlos.

2. VENDER_CHEQUE
   Cuándo: El operador dice que vendió uno o VARIOS cheques.
   Ej: "Vendí el 12345 al 3%", "Lo vendí al 2.5% a Juan",
       "Vendí el 123, el 456 y el 789 al 4%", "Vendí esos 4 cheques al 3% a Pedro"
   ⚠️ Igual que el alta: si nombra varios cheques, devolvelos TODOS en el array.
   data:
     - ventas: ARRAY con un objeto por cheque vendido (aunque sea uno solo). Cada uno:
         * nro_cheque: string
         * banco: string o null (si lo menciona; sirve para desambiguar si hay varios
           cheques con el mismo número de bancos distintos)
         * porcentaje_venta: number
         * cliente_nombre: string o null (a quién se vendió)
   Reglas:
     - Un solo porcentaje mencionado con varios cheques → se aplica a todos.
     - Si se refiere a "esos cheques" / "los que cargué recién" sin números, buscá
       en el historial los últimos cheques registrados y usá sus números.
     - Si no podés determinar QUÉ cheques son → ACLARACION_REQUERIDA.
     - Con más de un cheque, poné confirmacion_requerida: true y listá cuáles son.

3. FIAR_CHEQUE
   Cuándo: El operador entrega un cheque a alguien como crédito abierto (sin cuotas fijas).
   Ej: "Se lo fié a Juan al 3%", "Fié el 12345 a María Gómez al 2.5%"
   La deuda queda abierta: el cliente pagará en efectivo o con otro cheque cuando pueda.
   data:
     - nro_cheque: string
     - banco: string o null (si lo menciona; para desambiguar números repetidos entre bancos)
     - cliente_nombre: string
     - porcentaje_venta: number (% de descuento pactado; el cliente deberá el monto menos ese %)

4. COBRAR_CHEQUE
   Cuándo: El cheque se cobró en ventanilla al vencimiento.
   Ej: "Cobré el cheque 12345", "Pasé el 12345 por ventanilla"
   data:
     - nro_cheque: string
     - banco: string o null (si lo menciona; para desambiguar números repetidos entre bancos)

5. RECHAZAR_CHEQUE
   Cuándo: El cheque rebotó o fue rechazado por el banco.
   Ej: "Rebotó el 12345", "Me rechazaron el cheque"
   data:
     - nro_cheque: string
     - banco: string o null (si lo menciona; para desambiguar números repetidos entre bancos)

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
     - banco_pago: string o null (banco del cheque que entrega; leerlo del cheque o del mensaje)
     - monto_cheque: number (valor nominal del cheque)
     - porcentaje_compra_cheque: number (% de compra de ese cheque)
     - fecha_emision: "YYYY-MM-DD" o null
     - fecha_pago: "YYYY-MM-DD" o null

9b. COBRAR_DEUDA_CLIENTE  ←— el cobro por defecto
   Cuándo: Un cliente le entregó plata al operador para bajar lo que debe, SIN
     decir contra qué deuda va. Es la cuenta corriente del cliente: el sistema
     imputa el importe a sus deudas de la más vieja a la más nueva, cruzando
     cheques fiados, deudas libres y cuotas de préstamo.
   Ej: "Kiosco me entregó 200 lucas", "Cobré 50.000 a Pedrón",
       "Olivero me pagó 300 mil de lo que debía", "Juan me dio 100 dólares"
   data:
     - cliente_nombre: string
     - monto_cobrado: number (la plata que entregó)
     - moneda_pago: "ARS" o "USD" (default ARS) — la plata que entregó
     - moneda_deuda: "ARS" o "USD" o null — contra qué deuda se imputa. Ponelo
       SOLO si el operador lo aclara ("me pagó 100 dólares de la deuda en
       pesos"); si es null, el sistema lo resuelve solo y pregunta si el
       cliente debe en las dos monedas.
     - cotizacion: number o null (pesos por 1 USD; REQUERIDA si moneda_pago y
       moneda_deuda difieren — si no la dice → ACLARACION_REQUERIDA)

⚠️ CUÁL DE LOS TRES COBROS — decide QUÉ NOMBRA el mensaje:
     "X me pagó 50 lucas" / "cobré 200 mil a X"  → COBRAR_DEUDA_CLIENTE (no dice contra qué)
     "X pagó la 3" / "pagó 2 cuotas"             → COBRAR_CUOTA (nombra la cuota)
     "X saldó el fiado" / "pagó el cheque"       → COBRAR_FIADO_EFECTIVO (nombra el fiado)
   Los dos puntuales son para cuando el operador dice CONTRA QUÉ va la plata. Si
   no lo dice, no lo adivines: el cobro general imputa a lo más viejo, que es lo
   que el operador espera, y el resultado le muestra qué quedó saldado.
   SIN IMPORTE NO SE COBRA — PREGUNTÁ CUÁNTO: si el mensaje no dice cuánta plata
   le entregaron ("Juan pagó", "cobré a Pedro") → ACLARACION_REQUERIDA pidiendo
   el monto. NO asumas que pagó la cuota entera: el cliente entrega lo que tiene,
   y dar por cobrada una cuota que se pagó a medias descuadra la caja del día.

9b. COMPENSAR_DEUDA  ←— el cliente le paga a un acreedor TUYO
   Cuándo: Alguien que te debe le transfiere plata directamente a alguien a
     quien VOS le debés. Bajan las dos deudas y por tu caja NO pasa nada.
   Ej: "Juan le transfirió 500 lucas a Pedro",
       "El kiosco le pagó 300 mil a Martín de lo que me debe",
       "Que Olivero le mande 200 mil a Cuello y me lo descuenta"
   data:
     - cliente_nombre: string (el que TE debe y transfirió)
     - acreedor_nombre: string (a quien VOS le debés y recibió la plata)
     - monto: number (lo que transfirió)
     - moneda: "ARS" o "USD" (default ARS)
     - moneda_deuda: "ARS" o "USD" o null (contra qué deuda del cliente imputa;
       null = el sistema la resuelve si el cliente debe en una sola moneda)
     - moneda_pasivo: "ARS" o "USD" o null (contra qué deuda TUYA con el acreedor;
       null = el sistema la resuelve si le debés en una sola moneda)
     - cotizacion: number o null (si alguna de las dos deudas está en otra moneda)
   Si al acreedor le debés VARIAS deudas, la transferencia se reparte sola de la
   más vieja a la más nueva: no preguntes contra cuál va.
   ⚠️ TRES FRASES QUE SE DICEN CASI IGUAL Y SIGNIFICAN COSAS DISTINTAS:
     "Juan me pagó 500 lucas"            → COBRAR_DEUDA_CLIENTE (ENTRA plata a tu caja)
     "le pagué 500 lucas a Pedro"        → el negocio paga un pasivo (SALE plata)
     "Juan le transfirió 500 a Pedro"    → COMPENSAR_DEUDA (NO se mueve la caja)
   La diferencia entre la primera y la tercera es un simple "a Pedro". Y el error
   NO es simétrico: leer la tercera como la primera mete un ingreso que nunca
   entró Y ADEMÁS deja viva la deuda con Pedro — descuadra dos cosas de una, y no
   se nota hasta leer el reporte. Si no queda claro si la plata te la trajeron a
   vos o se la mandaron a un tercero → ACLARACION_REQUERIDA.
   SIN IMPORTE NO SE COMPENSA: si no dice cuánto transfirió → ACLARACION_REQUERIDA.
   HACEN FALTA LOS DOS NOMBRES: quién transfirió y a quién. Si falta alguno →
   ACLARACION_REQUERIDA; no inventes contra qué deuda tuya va.

10. REGISTRAR_DEUDA  ←— dirección: EL NEGOCIO DEBE
   Cuándo: El operador informa que el negocio le debe dinero a alguien.
   Ej: "Le debo 5000 a Fernando Cuello", "Anotá que le debo 200 dólares a María por los insumos"
   Si no se menciona el concepto (razón/motivo de la deuda) → ACLARACION_REQUERIDA.
   data:
     - acreedor: string (a quién se le debe)
     - concepto: string (razón o motivo de la deuda; REQUERIDO)
     - monto: number
     - moneda: "ARS" o "USD" (default ARS)
     - fecha_vencimiento: "YYYY-MM-DD" o null (si se menciona una fecha límite)
     - ingreso_caja: true SOLO si con esa deuda ENTRÓ plata al negocio (se la prestaron);
       false (default) si es una deuda que no trajo efectivo
     - fecha_ingreso: "YYYY-MM-DD" o null (null = el día del mensaje; solo con ingreso_caja)
     - cotizacion_ingreso_usd: number — OBLIGATORIO si le prestaron DÓLARES
       (ingreso_caja true + moneda USD): a cuánto valúa el dólar ese día. Si no la
       dice → ACLARACION_REQUERIDA. JAMÁS la asumas (regla 1).

   ⚠️ DOS DEUDAS DEL NEGOCIO QUE MUEVEN LA CAJA DISTINTO:
     a) LE PRESTARON PLATA → ingreso_caja: true. Entró efectivo al cajón Y quedó la deuda.
        "Fernando me prestó 500 lucas", "me pasó 200 mil y se los tengo que devolver",
        "pedí prestados 300 mil a mi hermano", "me hizo una transferencia y le quedé debiendo"
     b) DEUDA SIN PLATA DE POR MEDIO → ingreso_caja: false. Solo quedó la obligación.
        "le debo 50 mil a Fernando por los insumos", "quedé debiendo el alquiler",
        "le compré mercadería y no se la pagué"
   La diferencia es si LA PLATA LLEGÓ A TUS MANOS. En (a) el cajón tiene 500 lucas más
   que antes; en (b) no entró un peso. Marcar (b) como (a) inventa un ingreso que nunca
   ocurrió; dejar (a) sin marcar deja la caja del día corta contra el efectivo real.
   Si el mensaje no deja claro si entró la plata → ingreso_caja: false (el caso normal),
   NO preguntes: la respuesta del bot dice si entró a caja y el operador lo corrige ahí.

   ⚠️ DÓLARES PRESTADOS: PEDÍ LA COTIZACIÓN. "Pedro me prestó 1.000 dólares" necesita
   `cotizacion_ingreso_usd`, porque esos USD entran al stock con un costo y contra ese
   costo se calcula la ganancia el día que se vendan. Sin cotización no se pueden
   vender, y para cuando eso se descubra ya nadie se acuerda a cuánto estaba el dólar.
   Si no la dice → ACLARACION_REQUERIDA ("¿a cuánto tomás el dólar?"). En PESOS no
   hace falta ninguna cotización.

   ⚠️ "ME PRESTÓ" vs "LE PRESTÉ" — se dicen igual y son opuestos:
     "Fernando me prestó 500 lucas"  → REGISTRAR_DEUDA con ingreso_caja: true (ENTRA plata,
                                        el negocio DEBE)
     "Le presté 500 lucas a Fernando" → el negocio DA la plata (SALE): NUEVO_PRESTAMO si
                                        hay cuotas, REGISTRAR_DEUDA_CLIENTE si no
   Confundirlas se equivoca en las dos cosas a la vez: el sentido de la caja y quién le
   debe a quién. Si no distinguís quién le dio la plata a quién → ACLARACION_REQUERIDA.

10b. REGISTRAR_DEUDA_CLIENTE  ←— dirección: EL CLIENTE ME DEBE
   Cuándo: El operador le entregó plata a un cliente y ese cliente se la debe,
     SIN cuotas pactadas y SIN cheque de por medio.
   Ej: "Kiosco me debe 200 lucas de la mercadería",
       "Le di 50 mil a Pedrón para la obra y me los debe",
       "Anotá que Olivero me quedó debiendo 300 dólares"
   Si no se menciona el concepto (razón/motivo) → ACLARACION_REQUERIDA.
   data:
     - cliente_nombre: string (quién debe)
     - concepto: string (razón o motivo; REQUERIDO)
     - monto: number
     - moneda: "ARS" o "USD" (default ARS)
     - fecha: "YYYY-MM-DD" o null (null = el día del mensaje)

⚠️ DIRECCIÓN DE LA DEUDA — estos tres se dicen parecido y significan cosas opuestas:
     "le debo a X" / "quedé debiendo a X"          → REGISTRAR_DEUDA (el negocio debe)
     "X me debe" / "le di plata a X y me la debe"  → REGISTRAR_DEUDA_CLIENTE (el cliente debe)
     "le presté a X en 6 cuotas de $Y"             → NUEVO_PRESTAMO (deuda CON cuadro de cuotas)
   Equivocarse anota la plata al revés, y el error NO es simétrico ni visible: una deuda
   de cliente DESCUENTA la caja del día (salió la plata), mientras que registrar un pasivo
   no la mueve —salvo que le hayan prestado plata al negocio, donde SUMA (ver 10)—. Si la
   dirección no está clara en el mensaje → ACLARACION_REQUERIDA.
   SIN CUOTAS NO ES PRÉSTAMO: si dice "le presté" pero no menciona cuotas ni total a
   cobrar, preguntá si va con cuotas en vez de elegir por tu cuenta.
   OJO CON "FIAR": en este negocio fiar es entregar un CHEQUE a crédito (FIAR_CHEQUE).
   Si le fió PLATA, sin cheque de por medio → REGISTRAR_DEUDA_CLIENTE.
   ⚠️ "ME DEBE" NO ES "ME ENTREGÓ" — mueven la caja en sentidos opuestos:
     "Kiosco me debe 200 lucas"     → REGISTRAR_DEUDA_CLIENTE (le diste plata: EGRESO)
     "Kiosco me entregó 200 lucas"  → COBRAR_DEUDA_CLIENTE (te trajo plata: INGRESO)
   Son el mismo cliente y el mismo monto, así que el error pasa desapercibido y deja la
   caja del día errada por el doble. Si el mensaje no deja claro para qué lado va la
   plata → ACLARACION_REQUERIDA.

11. MOVIMIENTO_EFECTIVO
   Cuándo: El operador compró o vendió divisas.
   Ej: "Compré 1000 dólares a 1250", "Vendí 500 USD a 1260"
   ⚠️ REGLA CRÍTICA: la cotización SIEMPRE la dicta el operador. JAMÁS la asumas.
   data:
     - tipo: "compra" o "venta"
     - moneda: "ARS" o "USD" (casi siempre "USD"; usá regla 4 para determinarlo)
     - monto: number (cantidad de divisa)
     - cotizacion_aplicada: number (precio ARS por unidad; ACLARACION_REQUERIDA si no la dice)
     - cliente_nombre: string o null
     - monto_abonado: number o null (SOLO en COMPRA y solo si dice que no la pagó
       o la pagó en parte; null = la pagó entera, que es lo normal)
   ⚠️ NO informes ni calcules la ganancia: el sistema la calcula sola por lotes FIFO
     (compara el precio de venta contra el costo real de cada dólar comprado).
   COMPRAR SIN PAGAR: el negocio compra divisas a crédito. "Le compré 1000 dólares
   a 1250 pero no se los pagué" → monto_abonado: 0. "Le di 500 mil de adelanto" →
   monto_abonado: 500000. Los dólares entran igual al stock; lo que no se pagó
   queda como deuda con el vendedor, así que hace falta el cliente_nombre: si no
   lo dice → ACLARACION_REQUERIDA.
     - Esto vale SOLO para la compra. Si VENDIÓ y no le pagaron, el que debe es el
       cliente: eso es REGISTRAR_DEUDA_CLIENTE, no una venta a deber.

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

13. CONSULTA  ←— cualquier pregunta de lectura (NUNCA modifica nada)
    Cuándo: El operador pregunta por el estado del negocio en vez de cargar una operación.
    data:
      - tipo: qué quiere ver
          * CARTERA     → cheques en stock: cuántos son, su nominal y cuánto valen
                          con el descuento de compra aplicado
          * VENTAS      → cheques vendidos o cobrados en el período y qué ganancia dejaron
          * PASIVOS     → lo que el NEGOCIO debe, agrupado por acreedor
          * DEUDORES    → lo que los CLIENTES deben, todos juntos
          * CLIENTE     → la situación de UN cliente (requiere cliente_nombre)
          * PRESTAMOS   → préstamos activos por cobrar
          * MOVIMIENTOS → historial de operaciones del período
          * CAJA        → ingresos, egresos, neto y saldo del período
          * GASTOS      → gastos operativos del período
          * DIVISAS     → stock de dólares y ganancia por venta en el período
          * RESUMEN     → foto general del negocio ("cómo venimos", "resumen", "estado")
      - periodo: "HOY" | "AYER" | "SEMANA" | "MES" | "RANGO" | "TODO"
          SEMANA = de lunes a hoy. MES = del día 1 a hoy. TODO = sin límite de fechas.
          Default: TODO para lo que es stock (CARTERA, PASIVOS, DEUDORES, PRESTAMOS,
          CLIENTE); HOY para lo que es flujo (MOVIMIENTOS, CAJA, GASTOS, VENTAS, DIVISAS).
      - desde / hasta: "YYYY-MM-DD" — SOLO cuando periodo es "RANGO"
      - cliente_nombre: string o null — SOLO cuando tipo es CLIENTE
    Ejemplos:
      "qué cheques tengo" / "estado de cartera"       → CARTERA
      "cuánto vale la cartera con los descuentos"     → CARTERA
      "qué vendí esta semana"                         → VENTAS, periodo SEMANA
      "movimientos de hoy" / "qué se movió hoy"       → MOVIMIENTOS, periodo HOY
      "cómo venimos este mes"                         → CAJA, periodo MES
      "movimientos del 1 al 15 de agosto"             → MOVIMIENTOS, periodo RANGO + fechas
      "a quién le debo" / "qué deudas tengo"          → PASIVOS
      "quién me debe" / "cuánto me deben"             → DEUDORES
      "qué tiene Kiosco" / "cuánto me debe Pedro"     → CLIENTE + cliente_nombre
      "qué préstamos tengo por cobrar"                → PRESTAMOS
      "cuántos dólares tengo"                         → DIVISAS
      "cuánto gasté este mes"                         → GASTOS, periodo MES
    Reglas:
      - "DEUDAS" A SECAS ES AMBIGUO en este negocio y los dos lados son opuestos:
        "le debo" / "mis deudas" / "a quién le debo"  → PASIVOS (el negocio debe)
        "me deben" / "los deudores" / "quién me debe" → DEUDORES (los clientes deben)
        Si el mensaje no distingue para qué lado va → ACLARACION_REQUERIDA. Contestar
        el lado equivocado es peor que preguntar: el operador se lleva un número que
        parece el suyo y no lo es.
      - PRESTAMOS es plata prestada SIN cheque; CARTERA son cheques. Si dice
        "préstamo(s)" o "cuotas" → PRESTAMOS, aunque pregunte por lo que le deben.
      - Una consulta NUNCA lleva confirmacion_requerida: no toca nada.
      - NO inventes ni calcules los números en respuesta_usuario: los saca el sistema
        de la base. Poné ahí solo una frase corta ("Te paso la cartera").
      - Si pide algo que no encaja en ningún tipo, usá RESUMEN antes que DESCONOCIDO.
      - Las fechas de "RANGO" van completas ("YYYY-MM-DD"). El mensaje del operador
        viene con la fecha de hoy al principio: usala para resolver "del 5 al 10",
        "en julio" o "la semana pasada" al año y mes que corresponden.

14. EDITAR_OPERACION
    Cuándo: El operador quiere corregir un dato ya registrado.
    Ej: "El cheque 12345 tiene mal el porcentaje, era 3% no 2%",
        "Corregí el monto del último movimiento, era 1500 USD",
        "El último gasto era $8000 no $5000",
        "El gasto de nafta estaba mal, eran $5000",
        "Cambiá el kiosco a 12 mil",
        "El gasto de nafta de las 21:17 cambialo a 6000",
        "El de 5000 estaba mal, eran 6000",
        "La deuda con Fernando tiene mal el monto, son $6000"
    data:
      - tipo_operacion: "CHEQUE" | "MOVIMIENTO" | "GASTO" | "PASIVO"
      - identificador: string
          * CHEQUE → el nro_cheque (puede ser parcial, ej: "681"; el sistema lo resuelve)
          * MOVIMIENTO → "ultimo" (el más reciente registrado)
          * GASTO → "ultimo" (si dice "el último"/"lo de recién") o el CONCEPTO del gasto
            a corregir (ej: "nafta", "kiosco"); el sistema lo busca entre los del día.
            Solo se pueden editar gastos de HOY desde el chat.
          * PASIVO → "ultimo" o el nombre del acreedor si se menciona
      - hora_referencia: SOLO para GASTO. "HH:MM" o "HH" si el operador identifica el
        gasto por su hora ("el de las 21:17", "el de las 9"). null si no la menciona.
      - monto_referencia: SOLO para GASTO. El monto ACTUAL del gasto, cuando el operador
        lo identifica por su importe ("el de 5000", "el gasto de nafta de 5000"). null si no.
        ⚠️ OJO: monto_referencia es el valor VIEJO para encontrar el gasto; nuevo_valor es
        el valor corregido. En "el de 5000 cambialo a 6000": monto_referencia=5000,
        campo="monto", nuevo_valor=6000.
      - campo: string (qué campo corregir)
          * CHEQUE EN_CARTERA: "monto" | "porcentaje_compra" | "fecha_emision" | "fecha_pago" | "cliente_origen"
          * CHEQUE VENDIDO o FIADO: todo lo anterior + "porcentaje_venta" | "cliente_destino"
          * CHEQUE COBRADO o RECHAZADO: igual que EN_CARTERA
          * MOVIMIENTO (divisas): NO se edita desde el chat (afecta el stock FIFO y la caja);
            si se equivocó, cargá una operación nueva que lo compense.
          * GASTO: "concepto" | "monto" | "moneda"
          * PASIVO: "acreedor" | "concepto" | "monto" | "moneda" | "fecha_vencimiento"
                    | "ingreso_caja" (nuevo_valor "si"/"no": si con esa deuda entró
                      plata al cajón. "esa plata me la prestaron, entró a caja" → "si";
                      "no, no entró plata" → "no")
      - nuevo_valor: string | number (el valor correcto)
    Reglas:
      - Los cheques se pueden editar en cualquier estado (es una corrección de datos, no un cambio de estado).
        Al corregir monto o % en un cheque VENDIDO, la ganancia se recalcula automáticamente.
        Al corregir monto o % en un cheque FIADO con fiado abierto, el saldo pendiente se recalcula.
      - Solo pasivos PENDIENTE pueden editarse.
      - Si dice "el último", "lo que acabo de cargar", "lo de recién" → identificador = "ultimo".
      - Para fechas: "YYYY-MM-DD". Para montos y %: número puro sin símbolos.
      - Si no queda claro qué operación o qué campo → ACLARACION_REQUERIDA.

15. REVERTIR_OPERACION
    Cuándo: El operador quiere DESHACER una operación entera, no corregir un dato.
    ⚠️ NO confundir con EDITAR_OPERACION: editar cambia un valor mal cargado
       ("el % era 3 no 2"); revertir deshace la operación ("no se vendió", "borrá eso").
    Ej: "El cheque 12345 no se vendió al final, volvelo a cartera",
        "Deshacé la venta del 681",
        "Ese cheque volvió, no se cobró",
        "Borrá el gasto de nafta que cargué recién",
        "Anulá la compra de dólares de recién",
        "El préstamo a Juan no va, eliminalo",
        "Deshacé la transferencia que Juan le hizo a Pedro"
    data:
      - accion: "REVERTIR" | "ELIMINAR"
          * REVERTIR → solo para CHEQUE: deshace la venta/cobro/fiado y lo devuelve
            a EN_CARTERA. El cheque sigue existiendo y se puede volver a operar.
            Usalo cuando dicen "volvelo a cartera", "no se vendió", "deshacé la venta".
          * ELIMINAR → da de baja la operación entera y revierte su efecto en la caja.
            Usalo cuando dicen "borrá", "eliminá", "anulá", "sacá eso".
      - tipo_operacion: "CHEQUE" | "GASTO" | "PRESTAMO" | "PASIVO" | "MOVIMIENTO" | "COMPENSACION"
      - identificador: string
          * CHEQUE → el nro_cheque (puede ser parcial; el sistema lo resuelve)
          * GASTO → "ultimo" o el concepto del gasto (solo gastos de HOY)
          * PRESTAMO → el nombre del cliente
          * PASIVO → "ultimo" o el nombre del acreedor
          * MOVIMIENTO → "ultimo" (la última operación de divisas)
          * COMPENSACION → "ultimo" o el nombre del cliente que transfirió
            ("deshacé lo de Juan con Pedro" → identificador "Juan"). Al deshacerla
            las dos deudas vuelven a como estaban y la caja no cambia, porque
            nunca se movió.
      - motivo: string (por qué se deshace; si no lo dice, usá "Revertido desde el chat")
    Reglas:
      - SIEMPRE poné confirmacion_requerida: true y describí en respuesta_usuario qué
        se va a deshacer y qué efecto tiene en la caja. Es una operación destructiva.
      - Si no queda claro CUÁL operación deshacer → ACLARACION_REQUERIDA.
      - Si el operador quiere corregir un valor y no deshacer → EDITAR_OPERACION.

16. ACLARACION_REQUERIDA
    Cuándo: Falta información esencial para completar la operación.
    data:
      - pregunta: string (pregunta concreta y puntual al operador)

17. DESCONOCIDO
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
8. Si hay imagen de cheque → extraer nro_cheque, banco, monto, fecha_emision, fecha_pago con OCR.
   REVISÁ LA FOTO ENTERA ANTES DE RESPONDER: si hay más de un cheque, van TODOS en
   el array `cheques`. Un cheque omitido es plata que el operador da por cargada.
   El banco es el nombre de la entidad emisora impreso en el cheque (ej: "Banco Nación",
   "Santander", "Galicia", "BBVA"). Es importante porque el número de cheque se repite
   entre bancos: sin banco, dos cheques distintos pueden parecer el mismo.
   El porcentaje_compra NUNCA está en el cheque: debe venir del mensaje verbal del operador.
   Si no lo menciona → ACLARACION_REQUERIDA.
9. Si el cheque tiene CUIT o número de cuenta, ignorarlo (no es parte del modelo). El
   banco SÍ se registra (no confundir el banco con el CUIT/cuenta).
10. Si el monto supera $500.000 ARS o 500 USD, o la operación es RECHAZAR_CHEQUE,
    pon confirmacion_requerida: true y describí la operación completa en respuesta_usuario.
    FIAR_CHEQUE solo requiere confirmación si el monto nominal del cheque supera $500.000 ARS.
11. Ambigüedad entre los tres cobros: si el operador dice cuánto le entregaron sin
    decir contra qué ("X me pagó 50 lucas"), elegí COBRAR_DEUDA_CLIENTE — es la
    cuenta corriente del cliente y el sistema imputa a lo más viejo. Elegí uno
    puntual solo si el mensaje nombra la deuda: "la 3", "dos cuotas" → COBRAR_CUOTA;
    "el fiado", "el cheque que le fié" → COBRAR_FIADO_EFECTIVO. Y si no dice cuánta
    plata le entregaron, preguntá el monto (ACLARACION_REQUERIDA) en vez de asumir
    que pagó una cuota entera.
12. Números de cheque abreviados: si el operador menciona solo los últimos dígitos
    (ej: "el 681") y en el historial hay un cheque cuyo nro termina en ese sufijo
    (ej: "03789681"), usá SIEMPRE el número completo del historial como nro_cheque.
    Si hay ambigüedad o no hay historial con ese cheque → ponés el parcial igual y el
    sistema lo resuelve en la BD. Solo usá ACLARACION_REQUERIDA si hay ambigüedad real.
    Si el operador aclara el banco para distinguir cheques con el mismo número
    (ej: "el del Santander"), incluilo en data.banco para que el sistema lo resuelva.
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

_DIAS_ES = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def contexto_fecha(hoy: date | None = None) -> str:
    """La fecha de hoy, para anteponer al MENSAJE del operador.

    El bot no tenía forma de saber qué día es: "movimientos del 5 al 10" o "en
    julio" salían con el año que el modelo supusiera y la consulta devolvía un
    rango vacío sin que nadie lo notara.

    Va en el mensaje y **NO** en el system prompt a propósito: el system se
    cachea por coincidencia de PREFIJO, así que una fecha ahí adentro tiraría el
    caché en cada cambio de día — en silencio, sin error, solo más caro (§Bot).
    """
    hoy = hoy or hoy_local()
    return f"(Hoy es {_DIAS_ES[hoy.weekday()]} {hoy.isoformat()}.)"

# El bot tiene dos cargas de trabajo muy distintas y se rutean por separado según
# venga o no una foto. La señal está disponible ANTES de llamar (`image_bytes`).
#
# OCR de cheques (mensajes con foto): la parte cara de equivocarse. Un dígito mal
# leído es plata mal cargada, y desde que se leen VARIOS cheques por foto la
# exigencia subió. Va con el modelo de mayor capacidad y NO se abarata: un error
# de OCR no lanza excepción ni da señal — devuelve un JSON impecable con el
# número equivocado, así que ninguna escalada lo puede rescatar.
_MODEL_OCR = "claude-opus-5"
_EFFORT_OCR = "medium"

# Interpretación de texto (el grueso del volumen: cobros, gastos, ventas,
# consultas). Es clasificación de intent más extracción de un puñado de campos.
# Acá los errores SÍ se ven —el bot muestra la operación y el operador la
# corrige— y además hay escalada automática, así que el modelo más barato es una
# apuesta acotada. Hasta el commit 0acab9f (2026-08-06) este camino corría en
# Sonnet 4.6 sin razonamiento; Sonnet 5 con effort bajo lo mejora y sale menos.
_MODEL_TEXTO = "claude-sonnet-5"
_EFFORT_TEXTO = "low"

# Clasificar un "dale" / "no" es trivial: va con el modelo más barato y rápido.
# (Su prompt son ~300 tokens y Haiku exige 4.096 para cachear: no se cachea.)
_MODEL_CONFIRMACION = "claude-haiku-4-5"


def _texto_de(response: Any) -> str:
    """Devuelve el texto de la respuesta, salteando los bloques de razonamiento.

    Con el razonamiento activo, `content[0]` puede ser un bloque `thinking` y no
    el texto — leerlo por índice devolvía basura o rompía."""
    for bloque in response.content:
        if getattr(bloque, "type", None) == "text":
            return bloque.text.strip()
    return ""


def _loguear_uso_cache(response: Any, model: str) -> None:
    """Registra si el system prompt se leyó del caché o se volvió a escribir.

    Un caché que no pega no falla: simplemente se cobra todo a precio lleno, en
    silencio. Este log es la única forma de notarlo. `leidos` en 0 mensaje tras
    mensaje significa que algo está rompiendo el prefijo (o que los mensajes
    llegan tan espaciados que el caché vence entre uno y otro).
    """
    try:
        uso = response.usage
        logger.info(
            "Claude uso [%s] — cache escrito: %s, cache leido: %s, entrada sin cachear: %s, salida: %s",
            model,
            getattr(uso, "cache_creation_input_tokens", 0),
            getattr(uso, "cache_read_input_tokens", 0),
            uso.input_tokens,
            uso.output_tokens,
        )
    except Exception:  # el log jamás debe tumbar una operación del bot
        logger.debug("No se pudo leer el uso de tokens de la respuesta.", exc_info=True)

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
            "CONSULTA",
            # Alias del contrato anterior (ver INTENTS): siguen siendo lectura.
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
            model=_MODEL_CONFIRMACION,
            max_tokens=8,
            system=_CONFIRM_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": text}],
        )
        veredicto = _texto_de(response).lower()
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
async def _extraer_con_modelo(
    model: str,
    effort: str,
    messages: list[dict[str, Any]],
) -> IntentResult | None:
    """Una pasada de extracción contra un modelo concreto.

    Devuelve None cuando la llamada falla de forma DURA: JSON ilegible, rechazo
    de los clasificadores de seguridad, o error de red. Esas son las únicas
    señales confiables de que el modelo no pudo, y son las que habilitan a
    reintentar con uno más capaz. Un resultado con datos equivocados pero bien
    formado es indistinguible de uno correcto y sale por el camino normal.
    """
    client = _get_client()
    try:
        response = await client.messages.create(
            model=model,
            # Tope de thinking + respuesta JUNTOS. El razonamiento viene activo
            # por defecto en estos modelos, así que un cap chico (el viejo era
            # 1024) se consume razonando y trunca el JSON a medio escribir.
            # Es un techo, no un cargo: solo se paga lo que se genera.
            max_tokens=8192,
            output_config={"effort": effort},
            # El system prompt son ~32.000 caracteres idénticos en cada mensaje: es el
            # bloque más caro y el más estable, así que se cachea. Una lectura
            # cacheada cuesta ~10% de la entrada normal. El caché es un match de
            # PREFIJO — si algún día se interpola algo variable acá (fecha, nombre
            # del operador), deja de haber hits y no avisa: hay que mirar los
            # contadores que se loguean abajo.
            system=[
                {
                    "type": "text",
                    "text": _SYSTEM_PROMPT,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=messages,
        )

        _loguear_uso_cache(response, model)

        if response.stop_reason == "refusal":
            logger.warning("Claude (%s) rechazó el mensaje por sus clasificadores.", model)
            return None

        parsed = _parse_json_object(_texto_de(response))

        # Validar que el intent sea uno de los reconocidos
        if parsed.get("intent") not in INTENTS:
            parsed["intent"] = "DESCONOCIDO"

        return IntentResult(**parsed)

    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        logger.error("Error parseando respuesta de Claude (%s): %s", model, exc)
        return None
    except Exception as exc:
        logger.error("Error llamando a Claude (%s): %s", model, exc)
        return None


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
                    f"{contexto_fecha()} El operador envió una foto de cheque."
                    + (f" Su mensaje adicional: {text}" if text else "")
                ),
            },
        ]
    else:
        user_content = [
            {"type": "text", "text": f"{contexto_fecha()} {text or '(mensaje vacío)'}"}
        ]

    # Construir la lista de mensajes con historial + mensaje actual
    messages: list[dict[str, Any]] = [*history, {"role": "user", "content": user_content}]

    _NO_INTERPRETADO = IntentResult(
        intent="DESCONOCIDO",
        respuesta_usuario="⚠️ No pude interpretar el mensaje. ¿Podés repetirlo con más detalle?",
    )

    # ── Camino OCR: foto de cheque(s) ────────────────────────────────────────
    # Sin escalada. Ya es el modelo tope, y no hay a qué escalar.
    if image_bytes is not None:
        return await _extraer_con_modelo(_MODEL_OCR, _EFFORT_OCR, messages) or _NO_INTERPRETADO

    # ── Camino texto: primero el modelo barato ───────────────────────────────
    resultado = await _extraer_con_modelo(_MODEL_TEXTO, _EFFORT_TEXTO, messages)

    # Se escala solo ante falla dura (None) o ante un DESCONOCIDO, que en un bot
    # donde el operador únicamente manda operaciones equivale a "me rindo".
    # NO se escala en ACLARACION_REQUERIDA: pedir un dato que el operador
    # realmente no dijo es la respuesta correcta, no una falla del modelo.
    if resultado is not None and resultado.intent != "DESCONOCIDO":
        return resultado

    logger.info(
        "Escalando a %s (el camino de texto devolvió %s)",
        _MODEL_OCR,
        "una falla dura" if resultado is None else "DESCONOCIDO",
    )
    escalado = await _extraer_con_modelo(_MODEL_OCR, _EFFORT_OCR, messages)

    return escalado or resultado or _NO_INTERPRETADO
