"""Helpers de fecha/hora con zona horaria del negocio (Argentina).

Los timestamps se persisten en UTC, pero el operador piensa y opera en hora
local (UTC-3). Tomar `.date()` sobre un datetime UTC traspapela las operaciones
nocturnas al día siguiente (ej: 21:17 ART = 00:17 UTC del día posterior), dejándolas
fuera del cierre de caja. Estos helpers calculan SIEMPRE la fecha en hora local.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

TZ_LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")


def hoy_local() -> date:
    """Fecha de hoy en hora de Argentina (no la del servidor, que corre en UTC)."""
    return datetime.now(TZ_LOCAL).date()


def fecha_local(dt: datetime | None) -> date:
    """Convierte un datetime (UTC u otro) a la fecha calendario local de Argentina.

    Si `dt` es None devuelve la fecha local de hoy. Si es naive, se asume UTC.
    """
    if dt is None:
        return hoy_local()
    if dt.tzinfo is None:
        from datetime import timezone

        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TZ_LOCAL).date()
