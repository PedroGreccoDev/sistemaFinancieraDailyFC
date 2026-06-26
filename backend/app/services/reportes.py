from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cuota,
    CuotaEstado,
    Moneda,
    MovimientoCaja,
    Pasivo,
    PasivoEstado,
    Prestamo,
)
from app.schemas.reportes import (
    CajaLinea,
    CajaMoneda,
    CuotaCobradaHistorialItem,
    ReporteCajaRead,
    SaldoPasivos,
)
from app.services.exceptions import ValidationError


def _money(value: object) -> Decimal:
    if value is None:
        return Decimal("0.00")
    if isinstance(value, Decimal):
        return value.quantize(Decimal("0.01"))
    return Decimal(str(value)).quantize(Decimal("0.01"))


def get_reporte_caja(db: Session, desde: date, hasta: date) -> ReporteCajaRead:
    """Caja diaria de flujo real: ingresos y egresos efectivos por moneda.

    Lee el libro `movimientos_caja` filtrando por `fecha` (día local ART, ya
    almacenado como Date — sin conversión de zona horaria) y arma una caja por
    cada moneda con sus líneas detalladas, totales y neto.
    """
    if desde > hasta:
        raise ValidationError(
            f"El rango es inválido: 'desde' ({desde}) es posterior a 'hasta' ({hasta})."
        )

    movimientos = list(
        db.scalars(
            select(MovimientoCaja)
            .where(MovimientoCaja.fecha >= desde, MovimientoCaja.fecha <= hasta)
            .order_by(MovimientoCaja.fecha.asc(), MovimientoCaja.created_at.asc())
        )
    )

    def _caja(moneda: Moneda) -> CajaMoneda:
        propios = [m for m in movimientos if m.moneda == moneda]
        ingresos = sum(
            (m.monto for m in propios if m.tipo == CajaTipo.INGRESO), Decimal("0.00")
        )
        egresos = sum(
            (m.monto for m in propios if m.tipo == CajaTipo.EGRESO), Decimal("0.00")
        )
        lineas = [
            CajaLinea(
                fecha=m.fecha,
                categoria=m.categoria.value,
                tipo=m.tipo.value,
                monto=_money(m.monto),
                detalle=m.detalle,
                ganancia=None if m.ganancia is None else _money(m.ganancia),
                medio_pago=None if m.medio_pago is None else m.medio_pago.value,
                cotizacion=None if m.cotizacion is None else m.cotizacion,
            )
            for m in propios
        ]
        return CajaMoneda(
            moneda=moneda.value,
            ingresos_total=_money(ingresos),
            egresos_total=_money(egresos),
            neto=_money(ingresos - egresos),
            lineas=lineas,
        )

    ganancia_divisas = _money(
        sum(
            (
                m.ganancia
                for m in movimientos
                if m.categoria == CajaCategoria.VENTA_USD and m.ganancia is not None
            ),
            Decimal("0.00"),
        )
    )

    return ReporteCajaRead(
        desde=desde,
        hasta=hasta,
        ars=_caja(Moneda.ARS),
        usd=_caja(Moneda.USD),
        ganancia_divisas=ganancia_divisas,
        saldo_pasivos=_get_saldo_pasivos(db),
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
