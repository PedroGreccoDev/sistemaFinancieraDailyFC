from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

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
    cobros_cuotas_ars: Decimal
    cobros_cuotas_usd: Decimal


class CuotaCobradaHistorialItem(BaseModel):
    cuota_id: UUID
    prestamo_id: UUID
    cliente_id: UUID
    cliente_nombre: str
    numero_cuota: int
    monto: Decimal
    moneda: str
    fecha_cobro: date
    fecha_vencimiento: date
