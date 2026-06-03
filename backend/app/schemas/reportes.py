from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class ReporteGananciasRead(BaseModel):
    desde: date
    hasta: date
    ganancia_cheques: Decimal
    ganancia_prestamos: Decimal
    ganancia_movimientos_efectivo: Decimal
    total: Decimal

