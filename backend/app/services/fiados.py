from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Fiado,
    FiadoEstado,
    Moneda,
)
from app.core.fechas import hoy_local
from app.services import caja as svc_caja
from app.services import stock_usd as svc_stock
from app.services.conversion import calcular_reduccion_saldo
from app.schemas.cheques import ChequeRead, FiadoCobrarConChequeResponse
from app.schemas.fiados import (
    FiadoCobrarConChequeRequest,
    FiadoCobrarEfectivoRequest,
    FiadoRead,
)
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
)


def get_fiado(db: Session, fiado_id: uuid.UUID) -> Fiado:
    fiado = db.get(Fiado, fiado_id)
    if fiado is None:
        raise NotFoundError("Fiado no encontrado.")
    return fiado


def list_fiados(db: Session, estado: FiadoEstado | None = None) -> list[Fiado]:
    query = select(Fiado).where(Fiado.anulado_at.is_(None))
    if estado is not None:
        query = query.where(Fiado.estado == estado)
    return list(db.scalars(query.order_by(Fiado.created_at.desc())))


def imputar_cobro(
    db: Session,
    fiado: Fiado,
    *,
    reduccion: Decimal,
    fecha: date,
    monto_caja: Decimal | None,
    moneda_pago: Moneda,
    cotizacion: Decimal | None,
) -> bool:
    """Baja el saldo del fiado por `reduccion` (ARS) y asienta su línea de caja.

    **No commitea**: deja todo en la sesión para que el commit sea del servicio
    que orquesta la operación. Así el cobro consolidado por cliente
    (`svc_deudores`) puede tocar un fiado, una deuda libre y un préstamo en una
    sola transacción, sin duplicar acá las reglas de cada módulo.

    `monto_caja` es la plata que entró **por este fiado**, en `moneda_pago`;
    `None` significa que la operación no mueve caja —el cobro con cheque, donde
    la plata se reconoce recién al venderlo o cobrarlo—. `cotizacion` viene con
    valor solo si el cobro cruza monedas (la deuda del fiado es siempre ARS).

    Devuelve si el fiado quedó cancelado."""
    fiado.saldo_pendiente = (fiado.saldo_pendiente - reduccion).quantize(Decimal("0.01"))
    cancelado = fiado.saldo_pendiente == Decimal("0.00")
    if cancelado:
        fiado.estado = FiadoEstado.CANCELADO

    if monto_caja is None or monto_caja <= Decimal("0.00"):
        return cancelado

    # Cobrar un fiado hace entrar plata a la caja en la moneda efectivamente cobrada
    # (incluye parciales); la cotización queda para reporte/auditoría en el cruce.
    cliente_nombre = fiado.cliente.nombre if fiado.cliente else "—"
    detalle = f"Cobro fiado - {cliente_nombre}"
    if cotizacion is not None:
        detalle += f" ({reduccion} ARS @ {cotizacion})"
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=moneda_pago,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_FIADO,
        monto=monto_caja,
        referencia_tipo="fiado",
        referencia_id=fiado.id,
        detalle=detalle,
        cotizacion=cotizacion,
    )
    if moneda_pago == Moneda.USD:
        # Entraron dólares: van al stock con su costo o no se van a poder vender
        # (§Stock de dólares). Acá la cotización nunca falta —la deuda del fiado
        # es siempre en pesos, así que cobrar en USD ya cruza monedas y el
        # operador tuvo que declararla—.
        svc_stock.ingresar(
            db,
            monto=monto_caja,
            cotizacion=cotizacion,
            fecha=fecha,
            origen_tipo="fiado_cobro",
            origen_id=fiado.id,
            detalle=f"Stock por {detalle}",
        )
        db.flush()
        from app.services.movimientos import _reimputar_fifo

        _reimputar_fifo(db)
    return cancelado


def cobrar_con_efectivo(
    db: Session,
    fiado_id: uuid.UUID,
    payload: FiadoCobrarEfectivoRequest,
) -> Fiado:
    fiado = db.scalar(select(Fiado).where(Fiado.id == fiado_id).with_for_update())
    if fiado is None:
        raise NotFoundError("Fiado no encontrado.")
    if fiado.estado == FiadoEstado.CANCELADO:
        raise ConflictError("El fiado ya está cancelado.")

    # La deuda del fiado siempre está en ARS; el pago puede venir en otra moneda.
    # calcular_reduccion_saldo valida la cotización y que el pago no supere el saldo.
    es_cross = payload.moneda_pago != Moneda.ARS
    reduccion = calcular_reduccion_saldo(
        Moneda.ARS,
        fiado.saldo_pendiente,
        payload.moneda_pago,
        payload.monto_cobrado,
        payload.cotizacion,
    )

    imputar_cobro(
        db,
        fiado,
        reduccion=reduccion,
        fecha=hoy_local(),
        monto_caja=payload.monto_cobrado,
        moneda_pago=payload.moneda_pago,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    try:
        db.commit()
        db.refresh(fiado)
        return fiado
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro en efectivo.") from exc


def cobrar_con_cheque(
    db: Session,
    fiado_id: uuid.UUID,
    payload: FiadoCobrarConChequeRequest,
    created_at: datetime | None = None,
) -> FiadoCobrarConChequeResponse:
    fiado = db.scalar(select(Fiado).where(Fiado.id == fiado_id).with_for_update())
    if fiado is None:
        raise NotFoundError("Fiado no encontrado.")
    if fiado.estado == FiadoEstado.CANCELADO:
        raise ConflictError("El fiado ya está cancelado.")
    # Solo choca contra cheques VIVOS: uno anulado libera su número (índice único
    # parcial, migración 0017). Sin este filtro, un cheque dado de baja seguiría
    # bloqueando la recarga aunque la BD ya lo permita.
    ya_existe = db.scalar(
        select(Cheque).where(
            Cheque.nro_cheque == payload.nro_cheque_pago,
            Cheque.banco == payload.banco_pago,
            Cheque.anulado_at.is_(None),
        )
    )
    if ya_existe is not None:
        banco_txt = f" del banco {payload.banco_pago}" if payload.banco_pago else ""
        raise ConflictError(
            f"Ya existe un cheque Nº '{payload.nro_cheque_pago}'{banco_txt}."
        )

    valor_neto = (
        payload.monto_cheque * (Decimal("100") - payload.porcentaje_compra_cheque) / Decimal("100")
    ).quantize(Decimal("0.01"))

    # diferencia > 0: vos debés al cliente | diferencia < 0: el cliente aún debe
    diferencia = (valor_neto - fiado.saldo_pendiente).quantize(Decimal("0.01"))

    cheque_nuevo = Cheque(
        nro_cheque=payload.nro_cheque_pago,
        banco=payload.banco_pago,
        monto=payload.monto_cheque,
        porcentaje_compra=payload.porcentaje_compra_cheque,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        estado=ChequeEstado.EN_CARTERA,
        ganancia=Decimal("0.00"),
        cliente_origen_id=fiado.cliente_id,
    )
    if created_at is not None:
        cheque_nuevo.created_at = created_at

    if diferencia >= Decimal("0.00"):
        fiado.saldo_pendiente = Decimal("0.00")
        fiado.estado = FiadoEstado.CANCELADO
    else:
        fiado.saldo_pendiente = (-diferencia).quantize(Decimal("0.01"))

    try:
        db.add(cheque_nuevo)
        db.commit()
        db.refresh(fiado)
        db.refresh(cheque_nuevo)
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc

    return FiadoCobrarConChequeResponse(
        fiado=FiadoRead.model_validate(fiado),
        cheque_ingresado=ChequeRead.model_validate(cheque_nuevo),
        diferencia=diferencia,
    )
