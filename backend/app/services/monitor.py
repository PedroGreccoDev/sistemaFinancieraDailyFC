"""Monitor interno: vigila la salud del bot y avisa por Telegram.

Corre como una tarea de fondo del propio backend, así que cubre **todo lo que
se cae alrededor del proceso** (WAHA, la sesión de WhatsApp, Postgres) pero por
definición **no puede avisar si el proceso muere**. Ese caso lo cubre el
watchdog externo (`.github/workflows/healthcheck.yml`), que pega desde afuera a
`GET /health/deep`. Las dos capas son complementarias: sacar una deja un agujero.

Sobre correr una sola vez: el `entrypoint.sh` levanta uvicorn con un solo
worker. Si algún día se agregan workers, cada uno correría su propio monitor y
las alertas se duplicarían — ahí habría que moverlo a un proceso aparte.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings
from app.services import health, telegram

logger = logging.getLogger(__name__)

_tarea: asyncio.Task | None = None

# Antifloods de `alertar_error`: última vez que se avisó de cada clave de error.
_ultimo_error: dict[str, datetime] = {}
_VENTANA_ERROR = timedelta(minutes=15)


async def _ciclo() -> None:
    """Loop de vigilancia. Nunca muere por un chequeo fallido."""
    settings = get_settings()
    intervalo = max(30, settings.monitor_intervalo_segundos)
    repetir = timedelta(minutes=max(1, settings.monitor_repetir_minutos))

    # Margen de arranque: en un deploy, WAHA y Postgres pueden tardar en
    # aceptar conexiones y alertar de eso sería un falso positivo garantizado.
    await asyncio.sleep(settings.monitor_demora_inicial_segundos)

    if settings.monitor_avisar_arranque:
        await telegram.enviar_alerta(
            "🔄 <b>Backend iniciado</b> — el monitor de salud está corriendo.\n"
            f"🕒 {health.hora_ar(datetime.now(timezone.utc))}"
        )

    estado = health.EstadoAlerta()
    while True:
        try:
            diagnostico = await health.diagnosticar()
            decision = health.decidir_alerta(
                estado,
                diagnostico,
                umbral_fallos=max(1, settings.monitor_umbral_fallos),
                repetir_cada=repetir,
                alertar_degradado=settings.monitor_alertar_degradado,
            )
            estado = decision.estado

            if decision.aviso:
                nivel = logger.info if decision.recuperado else logger.error
                nivel("Monitor de salud: %s", diagnostico.firma or "recuperado")
                await telegram.enviar_alerta(decision.aviso)
            elif diagnostico.estado is not health.Estado.OK:
                logger.warning("Monitor de salud degradado: %s", diagnostico.firma)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — el monitor no puede morirse
            logger.exception("El monitor de salud falló en un ciclo: %s", exc)

        await asyncio.sleep(intervalo)


def iniciar() -> None:
    """Arranca la tarea de fondo (idempotente). Se llama en el `startup`."""
    global _tarea
    settings = get_settings()

    if not settings.monitor_activo:
        logger.info("Monitor de salud desactivado (MONITOR_ACTIVO=false)")
        return
    if not telegram.configurado():
        logger.warning(
            "Monitor de salud NO iniciado: falta TELEGRAM_BOT_TOKEN o TELEGRAM_CHAT_IDS"
        )
        return
    if _tarea is not None and not _tarea.done():
        return

    _tarea = asyncio.create_task(_ciclo(), name="monitor-salud")
    logger.info(
        "Monitor de salud iniciado (cada %ss, alerta tras %s fallos seguidos)",
        settings.monitor_intervalo_segundos,
        settings.monitor_umbral_fallos,
    )


async def detener() -> None:
    """Cancela la tarea de fondo. Se llama en el `shutdown`."""
    global _tarea
    if _tarea is None:
        return
    _tarea.cancel()
    try:
        await _tarea
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _tarea = None


async def alertar_error(clave: str, titulo: str, detalle: str) -> None:
    """Avisa por Telegram de un error puntual del bot (no de una caída).

    Sirve para lo que el chequeo periódico no ve: una operación que explotó
    procesando un mensaje real. `clave` agrupa errores repetidos — el mismo
    tipo de error no vuelve a avisar dentro de `_VENTANA_ERROR`, para que un
    problema sistemático no llene el chat de Telegram y tape lo demás.
    """
    if not telegram.configurado():
        return

    ahora = datetime.now(timezone.utc)
    previo = _ultimo_error.get(clave)
    if previo is not None and ahora - previo < _VENTANA_ERROR:
        return
    _ultimo_error[clave] = ahora

    await telegram.enviar_alerta(
        f"⚠️ <b>{telegram.escapar(titulo)}</b>\n\n"
        f"<pre>{telegram.escapar(detalle[:1500])}</pre>\n"
        f"🕒 {health.hora_ar(ahora)}"
    )
