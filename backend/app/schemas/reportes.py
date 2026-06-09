from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel


class SaldoPasivos(BaseModel):
    """Snapshot de pasivos pendientes al momento del arqueo (no filtrado por periodo)."""
    pendiente_ars: Decimal
    pendiente_usd: Decimal


class ReporteGananciasRead(BaseModel):
    desde: date
    hasta: date
    ganancia_cheques: Decimal
    ganancia_prestamos: Decimal
    ganancia_movimientos_efectivo: Decimal
    gastos_operativos: Decimal
    total_ganancias: Decimal
    neto: Decimal
    saldo_pasivos: SaldoPasivos
