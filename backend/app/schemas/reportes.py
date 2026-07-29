from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SaldoPasivos(BaseModel):
    """Snapshot de pasivos pendientes al momento del arqueo (no filtrado por periodo)."""
    pendiente_ars: Decimal
    pendiente_usd: Decimal


class CajaLinea(BaseModel):
    """Una línea de movimiento de caja (ingreso o egreso) dentro del período."""
    fecha: date
    categoria: str
    tipo: str  # INGRESO | EGRESO
    monto: Decimal
    detalle: str | None
    ganancia: Decimal | None  # solo VENTA_USD
    medio_pago: str | None  # solo PAGO_PASIVO: EFECTIVO | TRANSFERENCIA
    cotizacion: Decimal | None  # $/USD si el pago cruzó monedas


class CajaMoneda(BaseModel):
    """Caja de una moneda: totales de ingresos/egresos, neto y detalle de líneas."""
    moneda: str
    ingresos_total: Decimal
    egresos_total: Decimal
    neto: Decimal
    lineas: list[CajaLinea]


class ReporteCajaRead(BaseModel):
    """Caja diaria de flujo real: ingresos y egresos efectivos, separados por moneda."""
    desde: date
    hasta: date
    ars: CajaMoneda
    usd: CajaMoneda
    # Ganancia FIFO realizada por venta de divisas en el período (dato, no movimiento).
    ganancia_divisas: Decimal
    saldo_pasivos: SaldoPasivos


class MovimientoUnificadoRead(BaseModel):
    """Una operación del historial unificado de Movimientos.

    Feed completo de TODO lo que pasa en el negocio, venga del bot o del panel:
    - Toda fila del libro de caja (`movimientos_caja`): cobros (parciales y
      totales), ventas/compras/cobros de cheque, compra/venta de USD,
      otorgamientos, gastos, pagos de pasivo y vueltos.
    - Los ingresos de cheques a cartera (evento sin movimiento de efectivo).

    `flujo` = INGRESO | EGRESO (según el tipo de caja) | NEUTRO (eventos sin
    plata, como el ingreso de un cheque a cartera). `grupo` es la familia de
    operación para filtrar en el panel.
    """
    id: str
    fecha: date
    moneda: str  # ARS | USD
    grupo: str  # COBROS | CHEQUES | DIVISAS | GASTOS | OTORGAMIENTOS | PASIVOS
    categoria: str  # CajaCategoria original o INGRESO_CHEQUE
    flujo: str  # INGRESO | EGRESO | NEUTRO
    descripcion: str
    monto: Decimal
    ganancia: Decimal | None  # solo VENTA_USD
    medio_pago: str | None  # solo PAGO_PASIVO: EFECTIVO | TRANSFERENCIA
    cotizacion: Decimal | None  # $/USD si el pago cruzó monedas
    referencia_tipo: str | None
    referencia_id: UUID | None


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
