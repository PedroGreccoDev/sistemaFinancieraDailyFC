from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Cheque, ChequeEstado, MovimientoEfectivo, Prestamo
from app.schemas.reportes import ReporteGananciasRead


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

    return ReporteGananciasRead(
        desde=desde,
        hasta=hasta,
        ganancia_cheques=ganancia_cheques,
        ganancia_prestamos=ganancia_prestamos,
        ganancia_movimientos_efectivo=ganancia_movimientos,
        total=ganancia_cheques + ganancia_prestamos + ganancia_movimientos,
    )
