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
    ValidationError,
)


def get_fiado(db: Session, fiado_id: uuid.UUID) -> Fiado:
    fiado = db.get(Fiado, fiado_id)
    if fiado is None:
        raise NotFoundError("Fiado no encontrado.")
    return fiado


def list_fiados(db: Session, estado: FiadoEstado | None = None) -> list[Fiado]:
    query = select(Fiado)
    if estado is not None:
        query = query.where(Fiado.estado == estado)
    return list(db.scalars(query.order_by(Fiado.created_at.desc())))


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
    if payload.monto_cobrado > fiado.saldo_pendiente:
        raise ValidationError(
            f"El monto cobrado ({payload.monto_cobrado}) supera el saldo pendiente "
            f"({fiado.saldo_pendiente})."
        )

    fiado.saldo_pendiente = (fiado.saldo_pendiente - payload.monto_cobrado).quantize(Decimal("0.01"))
    if fiado.saldo_pendiente == Decimal("0.00"):
        fiado.estado = FiadoEstado.CANCELADO

    # Cobrar un fiado en efectivo hace entrar plata a la caja ARS (incluye parciales).
    cliente_nombre = fiado.cliente.nombre if fiado.cliente else "—"
    svc_caja.registrar(
        db,
        fecha=hoy_local(),
        moneda=Moneda.ARS,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_FIADO,
        monto=payload.monto_cobrado,
        referencia_tipo="fiado",
        referencia_id=fiado.id,
        detalle=f"Cobro fiado - {cliente_nombre}",
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
    ya_existe = db.scalar(
        select(Cheque).where(
            Cheque.nro_cheque == payload.nro_cheque_pago,
            Cheque.banco == payload.banco_pago,
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
