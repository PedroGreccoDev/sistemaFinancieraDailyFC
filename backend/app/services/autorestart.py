"""Auto-reinicio de la sesión de WhatsApp cuando queda `FAILED` o `STOPPED`.

La caída más frecuente del bot no es que WAHA se muera: es que la sesión quede
atrapada en `FAILED` después de un loop de reconexión. El gateway sigue vivo y
contestando, el backend sigue sano, y el bot está mudo hasta que alguien entra
al panel de WAHA y aprieta *restart*. Ese restart no pide QR —las credenciales
viven en el volumen—, así que es exactamente el tipo de trabajo que no tiene
por qué esperar a que un humano lea el Telegram.

Este módulo hace ese apretón solo, con tres frenos que importan más que la
función en sí:

1. **Nunca toca `SCAN_QR_CODE`.** Ese estado sí significa que el celular se
   desvinculó: no hay credencial que reanudar y reiniciar en loop no la
   devuelve. Ahí hace falta una persona con el teléfono en la mano.
2. **Nunca toca una sesión sana.** Solo actúa sobre `FAILED` y `STOPPED`.
3. **Se rinde.** Como máximo `autorestart_max_intentos` seguidos, espaciados
   por `autorestart_espera_minutos`. Un reintento infinito contra los
   servidores de WhatsApp es la forma más rápida de que baneen el número —el
   remedio sería peor que la caída—. Agotados los intentos se calla y deja
   que la alerta de `monitor.py` haga su trabajo.

La decisión (`decidir_reinicio`) es pura y está testeada; la parte que toca la
red (`intentar`) solo la ejecuta.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum

import httpx

from app.core.config import get_settings
from app.services import health, telegram

logger = logging.getLogger(__name__)

# Más corto que el del cliente de envío: acá nadie está esperando la respuesta,
# y un WAHA que tarda 30 s en aceptar un restart no va a arreglarse con más
# paciencia — se reintenta en el próximo ciclo del monitor.
_TIMEOUT = httpx.Timeout(15.0)


class Accion(str, Enum):
    """Qué hacer con la sesión en este ciclo."""

    NADA = "NADA"
    START = "START"  # sesión detenida: alcanza con reanudarla
    RESTART = "RESTART"  # sesión fallada: hay que darla vuelta entera


# Qué acción pide cada estado de sesión de WAHA. Lo que NO está acá —`WORKING`,
# `STARTING`, `SCAN_QR_CODE` y cualquier estado nuevo que invente WAHA— no se
# toca: la lista es blanca a propósito, para que una versión futura del gateway
# no active el reinicio automático por un estado que nadie evaluó.
_ACCION_POR_ESTADO: dict[str, Accion] = {
    "STOPPED": Accion.START,
    "FAILED": Accion.RESTART,
}


@dataclass(frozen=True)
class EstadoReinicio:
    """Memoria entre ciclos: cuántos intentos van y cuándo fue el último."""

    intentos: int = 0
    ultimo: datetime | None = None
    rendido: bool = False


def decidir_reinicio(
    previo: EstadoReinicio,
    status: str,
    ahora: datetime,
    *,
    max_intentos: int = 3,
    espera: timedelta = timedelta(minutes=5),
) -> tuple[Accion, EstadoReinicio]:
    """Decide si corresponde reiniciar la sesión. Función pura.

    Devuelve la acción y el estado nuevo. El contador se reinicia solo cuando
    la sesión vuelve a un estado que no pide nada: así una caída de la semana
    que viene arranca con los tres intentos de nuevo, en vez de encontrarse el
    cupo gastado por la caída de hoy.
    """
    accion = _ACCION_POR_ESTADO.get(status.upper(), Accion.NADA)

    if accion is Accion.NADA:
        # Incluye WORKING, STARTING y SCAN_QR_CODE: no hay nada que reiniciar
        # (o no se arregla reiniciando). Borrón y cuenta nueva.
        return Accion.NADA, EstadoReinicio()

    if previo.intentos >= max_intentos:
        # Ya se probó lo que había que probar. Se marca `rendido` una sola vez
        # para poder avisarlo sin repetirlo en cada ciclo.
        return Accion.NADA, EstadoReinicio(
            intentos=previo.intentos, ultimo=previo.ultimo, rendido=True
        )

    if previo.ultimo is not None and ahora - previo.ultimo < espera:
        # Todavía dentro de la ventana de gracia: a WAHA hay que darle tiempo
        # de terminar de levantar antes de volver a sacudirlo.
        return Accion.NADA, previo

    return accion, EstadoReinicio(intentos=previo.intentos + 1, ultimo=ahora)


def corresponde_mirar(diagnostico: health.Diagnostico) -> bool:
    """Si el diagnóstico da motivo para ir a consultar el estado de la sesión.

    Evita una request extra a WAHA cada dos minutos cuando todo anda bien: si
    `sesion_wa` está OK no hay nada que reiniciar. Si el chequeo ni siquiera
    llegó a correr (WAHA caído), tampoco: reiniciar una sesión en un gateway
    que no contesta no lleva a ningún lado.
    """
    for chequeo in diagnostico.chequeos:
        if chequeo.nombre == "sesion_wa":
            return chequeo.estado is not health.Estado.OK
    return False


async def _estado_sesion(base: str, headers: dict[str, str]) -> str:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        response = await client.get(base, headers=headers)
        response.raise_for_status()
        return str(response.json().get("status", ""))


async def intentar(previo: EstadoReinicio) -> EstadoReinicio:
    """Consulta el estado real de la sesión y, si corresponde, la reinicia.

    Nunca levanta: cualquier fallo se loguea y devuelve el estado sin tocar,
    para que un problema acá no pueda tumbar el loop del monitor —que es lo
    único que garantiza que el dueño se entere de la caída—.
    """
    settings = get_settings()
    if not settings.autorestart_activo:
        return previo

    base_url = settings.waha_api_url.rstrip("/")
    if not base_url or not settings.waha_api_key:
        return previo

    base = f"{base_url}/api/sessions/{settings.waha_session}"
    headers = {"X-Api-Key": settings.waha_api_key}
    ahora = datetime.now(timezone.utc)

    try:
        status = await _estado_sesion(base, headers)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Auto-reinicio: no se pudo leer el estado de la sesión: %s", exc)
        return previo

    accion, nuevo = decidir_reinicio(
        previo,
        status,
        ahora,
        max_intentos=max(1, settings.autorestart_max_intentos),
        espera=timedelta(minutes=max(1, settings.autorestart_espera_minutos)),
    )

    if accion is Accion.NADA:
        if nuevo.rendido and not previo.rendido:
            logger.error(
                "Auto-reinicio: la sesión sigue en %s tras %d intentos; hace falta una persona",
                status,
                nuevo.intentos,
            )
            await _avisar(
                f"🟠 <b>Auto-reinicio agotado</b> — la sesión sigue en "
                f"<b>{telegram.escapar(status)}</b> después de {nuevo.intentos} intento(s).\n"
                "Hay que entrar a WAHA a mano.\n"
                f"🕒 {health.hora_ar(ahora)}"
            )
        return nuevo

    verbo = "start" if accion is Accion.START else "restart"
    logger.warning(
        "Auto-reinicio: sesión en %s, ejecutando %s (intento %d)", status, verbo, nuevo.intentos
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.post(f"{base}/{verbo}", headers=headers)
            response.raise_for_status()
    except httpx.HTTPError as exc:
        logger.error("Auto-reinicio: el %s falló: %s", verbo, exc)
        await _avisar(
            f"🔴 <b>Auto-reinicio falló</b> — no se pudo hacer <code>{verbo}</code> "
            f"de la sesión (estaba en <b>{telegram.escapar(status)}</b>).\n"
            f"🕒 {health.hora_ar(ahora)}"
        )
        return nuevo

    # No se verifica acá si volvió a WORKING: el próximo ciclo del monitor lo
    # dice mejor, y darle 2 segundos y preguntar sería adivinar. Si no volvió,
    # el diagnóstico lo va a ver y el contador ya quedó incrementado.
    await _avisar(
        f"🔄 <b>Sesión reiniciada sola</b> — estaba en <b>{telegram.escapar(status)}</b> "
        f"y se ejecutó <code>{verbo}</code> (intento {nuevo.intentos}).\n"
        f"🕒 {health.hora_ar(ahora)}"
    )
    return nuevo


async def _avisar(texto: str) -> None:
    """Manda el aviso sin dejar que un fallo de Telegram corte el reinicio."""
    try:
        await telegram.enviar_alerta(texto)
    except Exception as exc:  # noqa: BLE001 — avisar es lo secundario acá
        logger.warning("Auto-reinicio: no se pudo avisar por Telegram: %s", exc)
