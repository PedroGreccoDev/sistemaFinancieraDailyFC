from __future__ import annotations

from datetime import UTC, date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    Cheque,
    ChequeEstado,
    Cuota,
    CuotaEstado,
    GastoOperativo,
    Moneda,
    MovimientoEfectivo,
    Pasivo,
    PasivoEstado,
    Prestamo,
)
from app.schemas.reportes import CuotaCobradaHistorialItem, ReporteGananciasRead, SaldoPasivos
from app.services.exceptions import ValidationError

# Los eventos se persisten en UTC, pero el operador elige fechas en hora local
# (Argentina). Convertimos los límites del día local a UTC para no traspapelar
# operaciones nocturnas al día equivocado en el cierre de caja.
_TZ_LOCAL = ZoneInfo("America/Argentina/Buenos_Aires")


def _money(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def get_reporte_ganancias(db: Session, desde: date, hasta: date) -> ReporteGananciasRead:
    if desde > hasta:
        raise ValidationError(
            f"El rango es inválido: 'desde' ({desde}) es posterior a 'hasta' ({hasta})."
        )

    # Día local completo [00:00 .. 23:59:59.999999] convertido a UTC para filtrar
    # las columnas datetime, que se guardan en UTC.
    desde_dt = datetime.combine(desde, time.min, tzinfo=_TZ_LOCAL).astimezone(UTC)
    hasta_dt = datetime.combine(hasta, time.max, tzinfo=_TZ_LOCAL).astimezone(UTC)

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
    cobros_cuotas = _money(
        db.scalar(
            select(func.coalesce(func.sum(Cuota.monto), 0)).where(
                Cuota.estado == CuotaEstado.COBRADA,
                Cuota.fecha_cobro >= desde,
                Cuota.fecha_cobro <= hasta,
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
        cobros_cuotas=cobros_cuotas,
    )


def get_cobros_cuotas_historial(
    db: Session,
    desde: date,
    hasta: date,
) -> list[CuotaCobradaHistorialItem]:
    cuotas = list(
        db.scalars(
            select(Cuota)
            .join(Cuota.prestamo)
            .options(joinedload(Cuota.prestamo).joinedload(Prestamo.cliente))
            .where(
                Cuota.estado == CuotaEstado.COBRADA,
                Cuota.fecha_cobro >= desde,
                Cuota.fecha_cobro <= hasta,
            )
            .order_by(Cuota.fecha_cobro.desc(), Cuota.updated_at.desc())
        )
    )
    return [
        CuotaCobradaHistorialItem(
            cuota_id=c.id,
            prestamo_id=c.prestamo_id,
            cliente_id=c.prestamo.cliente_id,
            cliente_nombre=c.prestamo.cliente.nombre,
            numero_cuota=c.numero_cuota,
            monto=c.monto,
            moneda=c.prestamo.moneda.value,
            fecha_cobro=c.fecha_cobro,
            fecha_vencimiento=c.fecha_vencimiento,
        )
        for c in cuotas
        if c.fecha_cobro is not None
    ]


def _get_saldo_pasivos(db: Session) -> SaldoPasivos:
    def _sum(moneda: Moneda) -> Decimal:
        return _money(
            db.scalar(
                select(func.coalesce(func.sum(Pasivo.saldo_pendiente), 0)).where(
                    Pasivo.estado == PasivoEstado.PENDIENTE,
                    Pasivo.moneda == moneda,
                )
            )
        )

    return SaldoPasivos(
        pendiente_ars=_sum(Moneda.ARS),
        pendiente_usd=_sum(Moneda.USD),
    )
