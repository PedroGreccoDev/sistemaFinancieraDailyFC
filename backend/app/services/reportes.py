from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Cheque,
    ChequeEstado,
    GastoOperativo,
    Moneda,
    MovimientoEfectivo,
    Pasivo,
    PasivoEstado,
    Prestamo,
)
from app.schemas.reportes import ReporteGananciasRead, SaldoPasivos


def _money(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def get_reporte_ganancias(db: Session, desde: date, hasta: date) -> ReporteGananciasRead:
    desde_dt = datetime.combine(desde, time.min, tzinfo=UTC)
    hasta_dt = datetime.combine(hasta, time.max, tzinfo=UTC)

    ganancia_cheques = _money(
        db.scalar(
            select(func.coalesce(func.sum(Cheque.ganancia), 0)).where(
                Cheque.estado == ChequeEstado.VENDIDO,
                Cheque.ultimo_evento_manual_at >= desde_dt,
                Cheque.ultimo_evento_manual_at <= hasta_dt,
            )
        )
    )
    ganancia_prestamos = _money(
        db.scalar(
            select(func.coalesce(func.sum(Prestamo.ganancia), 0)).where(
                Prestamo.created_at >= desde_dt,
                Prestamo.created_at <= hasta_dt,
            )
        )
    )
    ganancia_movimientos = _money(
        db.scalar(
            select(func.coalesce(func.sum(MovimientoEfectivo.ganancia), 0)).where(
                MovimientoEfectivo.fecha_operacion >= desde_dt,
                MovimientoEfectivo.fecha_operacion <= hasta_dt,
            )
        )
    )
    gastos = _money(
        db.scalar(
            select(func.coalesce(func.sum(GastoOperativo.monto), 0)).where(
                GastoOperativo.fecha_operacion >= desde,
                GastoOperativo.fecha_operacion <= hasta,
                GastoOperativo.moneda == Moneda.ARS,
            )
        )
    )

    total_ganancias = ganancia_cheques + ganancia_prestamos + ganancia_movimientos
    saldo_pasivos = _get_saldo_pasivos(db)

    return ReporteGananciasRead(
        desde=desde,
        hasta=hasta,
        ganancia_cheques=ganancia_cheques,
        ganancia_prestamos=ganancia_prestamos,
        ganancia_movimientos_efectivo=ganancia_movimientos,
        gastos_operativos=gastos,
        total_ganancias=total_ganancias,
        neto=total_ganancias - gastos,
        saldo_pasivos=saldo_pasivos,
    )


def _get_saldo_pasivos(db: Session) -> SaldoPasivos:
    def _sum(moneda: Moneda) -> Decimal:
        return _money(
            db.scalar(
                select(func.coalesce(func.sum(Pasivo.monto), 0)).where(
                    Pasivo.estado == PasivoEstado.PENDIENTE,
                    Pasivo.moneda == moneda,
                )
            )
        )

    return SaldoPasivos(
        pendiente_ars=_sum(Moneda.ARS),
        pendiente_usd=_sum(Moneda.USD),
    )
