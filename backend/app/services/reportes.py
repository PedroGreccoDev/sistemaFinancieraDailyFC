from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.core.fechas import fecha_local
from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
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
    MovimientoUnificadoRead,
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


# Familia de operación de cada categoría de caja, para el filtro del panel.
_GRUPO_POR_CATEGORIA: dict[CajaCategoria, str] = {
    CajaCategoria.COBRO_CUOTA:           "COBROS",
    CajaCategoria.COBRO_FIADO:           "COBROS",
    CajaCategoria.COBRO_DEUDA:           "COBROS",
    CajaCategoria.VENTA_CHEQUE:          "CHEQUES",
    CajaCategoria.COMPRA_CHEQUE:         "CHEQUES",
    CajaCategoria.COBRO_CHEQUE:          "CHEQUES",
    CajaCategoria.COMPRA_USD:            "DIVISAS",
    CajaCategoria.VENTA_USD:             "DIVISAS",
    CajaCategoria.GASTO:                 "GASTOS",
    CajaCategoria.OTORGAMIENTO_PRESTAMO: "OTORGAMIENTOS",
    CajaCategoria.OTORGAMIENTO_DEUDA:    "OTORGAMIENTOS",
    CajaCategoria.PAGO_PASIVO:           "PASIVOS",
    CajaCategoria.VUELTO_PASIVO:         "PASIVOS",
}

# Fallback de descripción cuando la línea de caja no trae `detalle`.
_LABEL_CATEGORIA: dict[CajaCategoria, str] = {
    CajaCategoria.COBRO_CUOTA:           "Cobro de cuota",
    CajaCategoria.COBRO_FIADO:           "Cobro de fiado",
    CajaCategoria.COBRO_DEUDA:           "Cobro de deuda",
    CajaCategoria.VENTA_CHEQUE:          "Venta de cheque",
    CajaCategoria.COMPRA_CHEQUE:         "Compra de cheque",
    CajaCategoria.COBRO_CHEQUE:          "Cobro de cheque",
    CajaCategoria.COMPRA_USD:            "Compra de USD",
    CajaCategoria.VENTA_USD:             "Venta de USD",
    CajaCategoria.GASTO:                 "Gasto",
    CajaCategoria.OTORGAMIENTO_PRESTAMO: "Otorgamiento de préstamo",
    CajaCategoria.OTORGAMIENTO_DEUDA:    "Otorgamiento de deuda",
    CajaCategoria.PAGO_PASIVO:           "Pago de deuda (pasivo)",
    CajaCategoria.VUELTO_PASIVO:         "Vuelto de pasivo",
}

_LABEL_ESTADO_CHEQUE: dict[ChequeEstado, str] = {
    ChequeEstado.EN_CARTERA: "en cartera",
    ChequeEstado.VENDIDO:    "vendido",
    ChequeEstado.FIADO:      "fiado",
    ChequeEstado.COBRADO:    "cobrado",
    ChequeEstado.RECHAZADO:  "rechazado",
}


def get_movimientos_unificados(
    db: Session,
    desde: date,
    hasta: date,
) -> list[MovimientoUnificadoRead]:
    """Historial unificado: TODA operación del negocio en el período.

    Fuente principal: el libro de caja `movimientos_caja` (toda entrada/salida
    de plata, venga del bot o del panel). Se le suma el ingreso de cheques a
    cartera, que es un evento sin movimiento de efectivo (flujo NEUTRO) y por
    eso no vive en el libro de caja. Ordenado por fecha descendente.
    """
    if desde > hasta:
        raise ValidationError(
            f"El rango es inválido: 'desde' ({desde}) es posterior a 'hasta' ({hasta})."
        )

    items: list[MovimientoUnificadoRead] = []

    # ── Líneas del libro de caja ──────────────────────────────────────────
    movimientos = list(
        db.scalars(
            select(MovimientoCaja)
            .where(MovimientoCaja.fecha >= desde, MovimientoCaja.fecha <= hasta)
            .order_by(MovimientoCaja.fecha.asc(), MovimientoCaja.created_at.asc())
        )
    )
    for m in movimientos:
        descripcion = m.detalle or _LABEL_CATEGORIA.get(m.categoria, m.categoria.value)
        items.append(
            MovimientoUnificadoRead(
                id=str(m.id),
                fecha=m.fecha,
                moneda=m.moneda.value,
                grupo=_GRUPO_POR_CATEGORIA.get(m.categoria, "OTROS"),
                categoria=m.categoria.value,
                flujo=m.tipo.value,  # INGRESO | EGRESO
                descripcion=descripcion,
                monto=_money(m.monto),
                ganancia=None if m.ganancia is None else _money(m.ganancia),
                medio_pago=None if m.medio_pago is None else m.medio_pago.value,
                cotizacion=None if m.cotizacion is None else m.cotizacion,
                referencia_tipo=m.referencia_tipo,
                referencia_id=m.referencia_id,
            )
        )

    # ── Ingreso de cheques a cartera (evento sin efectivo) ────────────────
    # `created_at` es un timestamp UTC; la fecha operativa es la local ART. Se
    # consulta con una ventana ensanchada un día por lado y se filtra exacto por
    # fecha local, para no traspapelar cheques cargados de noche.
    cheques = list(
        db.scalars(
            select(Cheque)
            .options(joinedload(Cheque.cliente_origen))
            .where(
                func.date(Cheque.created_at) >= desde - timedelta(days=1),
                func.date(Cheque.created_at) <= hasta + timedelta(days=1),
            )
            .order_by(Cheque.created_at.asc())
        )
    )
    for c in cheques:
        fecha = fecha_local(c.created_at)
        if fecha < desde or fecha > hasta:
            continue
        banco = f" — {c.banco}" if c.banco else ""
        cliente = c.cliente_origen.nombre if c.cliente_origen else None
        origen_txt = f" de {cliente}" if cliente else ""
        estado_txt = _LABEL_ESTADO_CHEQUE.get(c.estado, c.estado.value.lower())
        items.append(
            MovimientoUnificadoRead(
                id=f"cheque:{c.id}",
                fecha=fecha,
                moneda=Moneda.ARS.value,
                grupo="CHEQUES",
                categoria="INGRESO_CHEQUE",
                flujo="NEUTRO",
                descripcion=f"Ingreso cheque Nº {c.nro_cheque}{banco}{origen_txt} ({estado_txt})",
                monto=_money(c.monto),
                ganancia=None,
                medio_pago=None,
                cotizacion=None,
                referencia_tipo="cheque",
                referencia_id=c.id,
            )
        )

    # Fecha descendente; a igual fecha, primero las líneas de caja (id UUID) y
    # los cheques quedan intercalados de forma estable por su string id.
    items.sort(key=lambda it: (it.fecha, it.id), reverse=True)
    return items


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
