"""Job de recordatorios de cobranza (notificaciones proactivas vía WhatsApp).

Busca las cuotas pendientes que vencen hoy o que ya están vencidas y envía
un mensaje de plantilla al operador por cada una. Como es una notificación
proactiva (el bot escribe primero, posiblemente fuera de la ventana de 24h),
usa una PLANTILLA aprobada de Meta — no texto libre.

Pensado para correr una vez al día desde un Railway Cron:

    python -m app.jobs.recordatorios

La plantilla (por defecto `recordatorio_cuota`) debe estar aprobada en Meta con
4 placeholders en el cuerpo, por ejemplo:

    📅 Cobranza: cuota {{1}} de {{2}} por {{3}} (vence {{4}}).
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.config import get_settings
from app.db.models import Cuota, CuotaEstado, Prestamo, PrestamoEstado
from app.db.session import SessionLocal
from app.services.whatsapp import client as wa_client

logger = logging.getLogger(__name__)


def _fmt_monto(monto: Decimal) -> str:
    """Formato de moneda argentino: 15.000,50"""
    s = f"{monto:,.2f}"
    return "$" + s.replace(",", "X").replace(".", ",").replace("X", ".")


def _recordatorios_de_hoy(db, hoy: date) -> list[tuple[str, str, str, str]]:
    """Devuelve (numero_cuota, cliente, monto, fecha) de cuotas a recordar.

    Incluye cuotas pendientes que vencen hoy o que ya vencieron, de préstamos
    que no estén cancelados.
    """
    stmt = (
        select(Cuota)
        .join(Cuota.prestamo)
        .options(joinedload(Cuota.prestamo).joinedload(Prestamo.cliente))
        .where(
            Cuota.estado == CuotaEstado.PENDIENTE,
            Cuota.fecha_vencimiento <= hoy,
            Prestamo.estado != PrestamoEstado.CANCELADO,
        )
        .order_by(Cuota.fecha_vencimiento.asc())
    )
    cuotas = db.scalars(stmt).unique().all()
    return [
        (
            f"#{c.numero_cuota}",
            c.prestamo.cliente.nombre,
            _fmt_monto(c.monto),
            c.fecha_vencimiento.isoformat(),
        )
        for c in cuotas
    ]


async def enviar_recordatorios() -> int:
    """Envía un recordatorio por cada cuota pendiente vencida/que vence hoy.

    Returns:
        Cantidad de recordatorios enviados con éxito.
    """
    settings = get_settings()
    operador = settings.whatsapp_operator_phone.strip()
    if not operador:
        logger.warning("WHATSAPP_OPERATOR_PHONE no configurado — no se envían recordatorios.")
        return 0

    hoy = date.today()
    db = SessionLocal()
    try:
        recordatorios = _recordatorios_de_hoy(db, hoy)
    finally:
        db.close()

    if not recordatorios:
        logger.info("No hay cuotas vencidas o que venzan hoy (%s).", hoy.isoformat())
        return 0

    enviados = 0
    for params in recordatorios:
        ok = await wa_client.send_template(
            operador,
            settings.whatsapp_recordatorio_template,
            list(params),
            settings.whatsapp_template_lang,
        )
        if ok:
            enviados += 1

    logger.info("Recordatorios enviados: %d/%d.", enviados, len(recordatorios))
    return enviados


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )
    asyncio.run(enviar_recordatorios())


if __name__ == "__main__":
    main()
