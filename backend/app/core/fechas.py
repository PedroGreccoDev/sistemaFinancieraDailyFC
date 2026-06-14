"""Helpers de fecha/hora con zona horaria del negocio (Argentina).

Los timestamps se persisten en UTC, pero el operador piensa y opera en hora
local (UTC-3). Tomar `.date()` sobre un datetime UTC traspapela las operaciones
nocturnas al día siguiente (ej: 21:17 ART = 00:17 UTC del día posterior), dejándolas
fuera del cierre de caja. Estos helpers calculan SIEMPRE la fecha en hora local.
"""

from __future__ import annotations

from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo

TZ_LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")


def datetime_local(dt: datetime | None) -> datetime:
    """Convierte un datetime (UTC u otro) a hora local de Argentina (aware).

    Si `dt` es None devuelve el ahora local. Si es naive, se asume UTC.
    """
    if dt is None:
        return datetime.now(TZ_LOCAL)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_LOCAL)


def hoy_local() -> date:
    """Fecha de hoy en hora de Argentina (no la del servidor, que corre en UTC)."""
    return datetime.now(TZ_LOCAL).date()


def fecha_local(dt: datetime | None) -> date:
    """Fecha calendario local de Argentina para `dt` (hoy local si es None)."""
    return datetime_local(dt).date()


def hora_local(dt: datetime | None) -> time:
    """Hora local de Argentina para `dt` (ahora local si es None)."""
    return datetime_local(dt).time().replace(microsecond=0)
