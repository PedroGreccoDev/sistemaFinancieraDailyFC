"""Diagnóstico de salud del sistema — qué está caído y por qué.

"El bot se cayó" no es un solo evento: son cuatro piezas independientes que
pueden fallar por separado, y cada una se arregla distinto.

    1. `base_datos`  — Postgres no responde → no se puede registrar nada.
    2. `waha`        — el gateway de WhatsApp no responde (contenedor caído).
    3. `sesion_wa`   — WAHA vivo pero la sesión se desvinculó del celular
                       (`SCAN_QR_CODE` / `FAILED` / `STOPPED`) → hay que
                       re-escanear el QR. **Es la caída más frecuente.**
    4. `webhook_wa`  — la sesión está `WORKING` pero WAHA perdió la URL del
                       webhook: el bot "está bien" y no recibe un solo mensaje.
                       Sin este chequeo la caída es invisible desde afuera.

Este módulo solo **diagnostica**. Quién avisa y cada cuánto vive en
`services/monitor.py`; el endpoint público está en `api/routes/health.py`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum

import httpx
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

# Corto a propósito: el diagnóstico corre cada pocos minutos y una pieza que
# tarda 8 s en contestar ya está rota para el operador que espera respuesta.
_TIMEOUT = httpx.Timeout(8.0)


class Estado(str, Enum):
    """Severidad de un chequeo. El estado global es el peor de los chequeos."""

    OK = "OK"
    DEGRADADO = "DEGRADADO"  # funciona a medias o algo no se pudo verificar
    CAIDO = "CAIDO"  # el bot no puede operar


_ORDEN = {Estado.OK: 0, Estado.DEGRADADO: 1, Estado.CAIDO: 2}

# Cómo se lee cada estado de sesión de WAHA. El texto va tal cual al mensaje de
# Telegram: tiene que decirle al que lo lee a las 3 AM qué hacer.
_ESTADOS_WAHA: dict[str, tuple[Estado, str]] = {
    "WORKING": (Estado.OK, "sesión de WhatsApp conectada"),
    "STARTING": (Estado.DEGRADADO, "la sesión está arrancando"),
    "STOPPED": (Estado.CAIDO, "la sesión está DETENIDA: el bot no recibe mensajes"),
    "SCAN_QR_CODE": (
        Estado.CAIDO,
        "la sesión se desvinculó del celular y pide QR: hay que volver a escanearlo en WAHA",
    ),
    "FAILED": (Estado.CAIDO, "la sesión falló: hay que reiniciarla en WAHA"),
}


@dataclass(frozen=True)
class Chequeo:
    """Resultado de verificar una pieza."""

    nombre: str
    estado: Estado
    detalle: str


@dataclass(frozen=True)
class Diagnostico:
    """Foto de salud completa: el estado global y el detalle de cada pieza."""

    estado: Estado
    chequeos: tuple[Chequeo, ...]
    momento: datetime

    @property
    def problemas(self) -> tuple[Chequeo, ...]:
        """Chequeos que no están en OK, del más grave al menos grave."""
        malos = [c for c in self.chequeos if c.estado is not Estado.OK]
        return tuple(sorted(malos, key=lambda c: -_ORDEN[c.estado]))

    @property
    def firma(self) -> str:
        """Identifica *qué* está fallando, para no repetir la misma alerta.

        Cambia cuando cambia el conjunto de piezas rotas (o su severidad): eso
        es una situación nueva y merece un aviso aunque ya hubiera una alerta
        abierta.
        """
        return "|".join(f"{c.nombre}:{c.estado.value}" for c in self.problemas)

    def to_dict(self, *, detallado: bool = True) -> dict:
        """Serializa el diagnóstico. `detallado=False` omite los `detalle`.

        Los detalles cuentan cómo está armada la infra (a qué URL apunta el
        webhook, qué host de Postgres no contesta). Es justo lo que necesita el
        watchdog para avisar algo útil, y justo lo que no debería leer un
        desconocido: el resumen alcanza para saber si el bot está vivo.
        """
        chequeos = []
        for c in self.chequeos:
            item = {"nombre": c.nombre, "estado": c.estado.value}
            if detallado:
                item["detalle"] = c.detalle
            chequeos.append(item)

        return {
            "estado": self.estado.value,
            "momento": self.momento.isoformat(),
            "chequeos": chequeos,
        }


def combinar(chequeos: list[Chequeo] | tuple[Chequeo, ...]) -> Estado:
    """Estado global = el peor de los chequeos (función pura)."""
    if not chequeos:
        return Estado.OK
    return max((c.estado for c in chequeos), key=lambda e: _ORDEN[e])


# ── Chequeos individuales ───────────────────────────────────────────────────


def chequear_base_datos() -> Chequeo:
    """`SELECT 1` contra Postgres. Sin BD no se puede registrar ni consultar nada."""
    db = SessionLocal()
    try:
        db.execute(text("SELECT 1"))
        return Chequeo("base_datos", Estado.OK, "responde")
    except Exception as exc:  # noqa: BLE001 — cualquier fallo acá es "la BD no está"
        # El texto crudo de psycopg trae host, puerto y usuario de la conexión.
        # Eso va al log de Railway, que es donde se debuggea; en la respuesta y
        # en la alerta alcanza con el tipo de error.
        logger.error("Chequeo de base de datos falló: %s", exc)
        return Chequeo("base_datos", Estado.CAIDO, f"no responde ({type(exc).__name__})")
    finally:
        db.close()


def interpretar_sesion(status: str) -> Chequeo:
    """Traduce el `status` de la sesión de WAHA a un chequeo (función pura)."""
    estado, detalle = _ESTADOS_WAHA.get(
        status.upper(),
        (Estado.DEGRADADO, f"estado de sesión desconocido: {status!r}"),
    )
    return Chequeo("sesion_wa", estado, detalle)


# Path del webhook del bot (`webhook.router` + la ruta). Se compara SOLO el path
# y no la URL entera: en el monorepo de Railway, WAHA puede apuntar legítimamente
# a la red interna (`backend.railway.internal`) en vez de al dominio público, y
# marcar eso como error sería una alerta falsa cada 30 minutos.
_PATH_WEBHOOK = "/webhook/whatsapp"


def interpretar_webhook(config: dict | None, url_esperada: str = "") -> Chequeo:
    """Verifica que WAHA siga teniendo configurado el webhook hacia el backend.

    Es el chequeo que atrapa la caída silenciosa: sesión `WORKING`, gateway
    sano y ni un mensaje llegando porque WAHA se reinició sin su config.

    Tolerante a propósito: si la respuesta no trae `config.webhooks` (versión
    distinta de WAHA), devuelve OK en vez de inventar una caída. Y si hay
    webhooks pero ninguno apunta al bot, avisa **DEGRADADO**, no CAIDO: puede
    ser un webhook a otro sistema conviviendo con el nuestro.

    `url_esperada` se acepta solo para dejar el dato en el mensaje; la decisión
    la toma el path (ver `_PATH_WEBHOOK`).
    """
    if not config or "webhooks" not in config:
        return Chequeo("webhook_wa", Estado.OK, "sin datos de webhook para verificar")

    webhooks = config.get("webhooks") or []
    if not webhooks:
        return Chequeo(
            "webhook_wa",
            Estado.CAIDO,
            "WAHA no tiene NINGÚN webhook configurado: los mensajes no llegan al backend",
        )

    urls = [str(w.get("url", "")) for w in webhooks if isinstance(w, dict)]
    if not any(_PATH_WEBHOOK in u for u in urls):
        return Chequeo(
            "webhook_wa",
            Estado.DEGRADADO,
            f"ningún webhook de WAHA apunta a {_PATH_WEBHOOK}: los mensajes no llegan al bot",
        )

    return Chequeo("webhook_wa", Estado.OK, f"{len(webhooks)} webhook(s) configurado(s)")


async def chequear_whatsapp() -> list[Chequeo]:
    """Consulta WAHA una sola vez y deriva los chequeos de gateway, sesión y webhook.

    Una sola request porque las tres cosas viajan en la misma respuesta de
    `GET /api/sessions/{session}` y no tiene sentido pegarle tres veces.
    """
    settings = get_settings()
    base = settings.waha_api_url.rstrip("/")

    if not base or not settings.waha_api_key:
        return [Chequeo("waha", Estado.DEGRADADO, "WAHA sin configurar (falta URL o API key)")]

    url = f"{base}/api/sessions/{settings.waha_session}"
    headers = {"X-Api-Key": settings.waha_api_key}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        codigo = exc.response.status_code
        detalle = (
            f"la sesión {settings.waha_session!r} no existe en WAHA (404)"
            if codigo == 404
            else f"respondió HTTP {codigo}"
        )
        return [Chequeo("waha", Estado.CAIDO, detalle)]
    except (httpx.HTTPError, ValueError) as exc:
        return [Chequeo("waha", Estado.CAIDO, f"no responde: {exc}")]

    chequeos = [Chequeo("waha", Estado.OK, "el gateway responde")]
    chequeos.append(interpretar_sesion(str(data.get("status", ""))))

    # El webhook solo importa si la sesión está operativa: con la sesión rota,
    # avisar además del webhook es ruido sobre el problema real.
    if chequeos[-1].estado is Estado.OK:
        chequeos.append(interpretar_webhook(data.get("config"), _url_webhook_esperada()))

    return chequeos


def chequear_configuracion() -> list[Chequeo]:
    """Config imprescindible para que el bot pueda operar (no requiere red).

    Separa lo que **impide operar** de lo que solo recorta una función: sin
    `ANTHROPIC_API_KEY` el bot no entiende un solo mensaje, mientras que sin
    `OPENAI_API_KEY` sigue trabajando por texto y solo pierde los audios.
    """
    settings = get_settings()
    chequeos: list[Chequeo] = []

    criticas = []
    if not settings.anthropic_api_key:
        criticas.append("ANTHROPIC_API_KEY (el bot no puede interpretar mensajes)")
    if not settings.whatsapp_operator_phone.strip():
        criticas.append("WHATSAPP_OPERATOR_PHONE (ignora todos los mensajes)")

    if criticas:
        chequeos.append(Chequeo("configuracion", Estado.CAIDO, "falta " + "; ".join(criticas)))
    elif not settings.openai_api_key:
        chequeos.append(
            Chequeo("configuracion", Estado.DEGRADADO, "falta OPENAI_API_KEY: no transcribe audios")
        )
    else:
        chequeos.append(Chequeo("configuracion", Estado.OK, "completa"))

    return chequeos


def _url_webhook_esperada() -> str:
    base = get_settings().public_base_url.rstrip("/")
    return f"{base}/webhook/whatsapp" if base else ""


async def diagnosticar() -> Diagnostico:
    """Corre todos los chequeos y arma el diagnóstico global.

    El `SELECT 1` va en un thread para no bloquear el event loop mientras la
    BD tarda en contestar (que es justo lo que pasa cuando está por caerse).
    """
    chequeos: list[Chequeo] = []

    resultados = await asyncio.gather(
        chequear_whatsapp(),
        asyncio.to_thread(chequear_base_datos),
        return_exceptions=True,
    )
    for resultado in resultados:
        if isinstance(resultado, BaseException):
            logger.exception("Chequeo de salud falló inesperadamente: %s", resultado)
            chequeos.append(Chequeo("interno", Estado.DEGRADADO, f"chequeo falló: {resultado}"))
        elif isinstance(resultado, Chequeo):
            chequeos.append(resultado)
        else:
            chequeos.extend(resultado)

    chequeos.extend(chequear_configuracion())

    return Diagnostico(
        estado=combinar(chequeos),
        chequeos=tuple(chequeos),
        momento=datetime.now(timezone.utc),
    )


# ── Decisión de alertar (pura, sin red ni reloj propio) ─────────────────────


@dataclass(frozen=True)
class EstadoAlerta:
    """Memoria del monitor entre chequeos: qué alerta hay abierta y desde cuándo."""

    fallos_consecutivos: int = 0
    firma_notificada: str | None = None
    ultima_notificacion: datetime | None = None


@dataclass(frozen=True)
class Decision:
    """Qué hacer tras un chequeo: el estado nuevo y, si corresponde, qué avisar."""

    estado: EstadoAlerta
    aviso: str | None = None
    recuperado: bool = False


def decidir_alerta(
    previo: EstadoAlerta,
    diagnostico: Diagnostico,
    *,
    umbral_fallos: int = 2,
    repetir_cada: timedelta = timedelta(minutes=30),
) -> Decision:
    """Decide si este diagnóstico merece un mensaje de Telegram. Función pura.

    Reglas, todas para que la alerta signifique algo cuando llega:

    - **Nada de alertar al primer fallo** (`umbral_fallos`): un timeout suelto
      de WAHA es normal y se recupera solo. Alertar por eso entrena al dueño a
      ignorar las alertas, que es peor que no tenerlas.
    - **Una alerta por caída, no una por chequeo**: mientras siga fallando lo
      mismo (misma `firma`) se recuerda recién cada `repetir_cada`.
    - **Si cambia qué está roto, se avisa enseguida**: pasar de "sesión caída"
      a "sesión caída + BD caída" es información nueva.
    - **Siempre se avisa la recuperación**, pero solo si hubo alerta abierta:
      sin eso nadie sabe si el problema sigue.

    `DEGRADADO` cuenta como falla: son avisos accionables (falta una API key,
    el webhook apunta a otro lado) y no se resuelven solos.
    """
    ahora = diagnostico.momento

    if diagnostico.estado is Estado.OK:
        if previo.firma_notificada is not None:
            return Decision(estado=EstadoAlerta(), aviso=_texto_recuperado(diagnostico), recuperado=True)
        return Decision(estado=EstadoAlerta())

    fallos = previo.fallos_consecutivos + 1
    firma = diagnostico.firma

    if fallos < umbral_fallos:
        # Todavía puede ser transitorio: contamos y esperamos al próximo chequeo.
        return Decision(estado=replace(previo, fallos_consecutivos=fallos))

    cambio = firma != previo.firma_notificada
    vencido = (
        previo.ultima_notificacion is not None
        and ahora - previo.ultima_notificacion >= repetir_cada
    )
    if cambio or vencido:
        nuevo = EstadoAlerta(
            fallos_consecutivos=fallos,
            firma_notificada=firma,
            ultima_notificacion=ahora,
        )
        return Decision(estado=nuevo, aviso=_texto_caida(diagnostico, repetido=not cambio))

    return Decision(estado=replace(previo, fallos_consecutivos=fallos))


def _texto_caida(diagnostico: Diagnostico, *, repetido: bool = False) -> str:
    from app.services.telegram import escapar  # import local: evita ciclo de imports

    titulo = "🔴 <b>BOT CAÍDO</b>" if diagnostico.estado is Estado.CAIDO else "🟠 <b>BOT DEGRADADO</b>"
    if repetido:
        titulo += " (sigue igual)"

    lineas = [titulo, ""]
    for chequeo in diagnostico.problemas:
        icono = "🔴" if chequeo.estado is Estado.CAIDO else "🟠"
        lineas.append(f"{icono} <b>{escapar(chequeo.nombre)}</b>: {escapar(chequeo.detalle)}")

    ok = [c.nombre for c in diagnostico.chequeos if c.estado is Estado.OK]
    if ok:
        lineas += ["", f"✅ OK: {escapar(', '.join(ok))}"]
    lineas += ["", f"🕒 {hora_ar(diagnostico.momento)}"]
    return "\n".join(lineas)


def _texto_recuperado(diagnostico: Diagnostico) -> str:
    return f"🟢 <b>BOT RECUPERADO</b> — todo vuelve a responder.\n\n🕒 {hora_ar(diagnostico.momento)}"


def hora_ar(momento: datetime) -> str:
    from app.core.fechas import datetime_local

    return datetime_local(momento).strftime("%d/%m/%Y %H:%M:%S") + " ART"
