from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    Cheque,
    ChequeEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    Pasivo,
    PasivoEstado,
)
from app.core.fechas import hoy_local
from app.schemas.pasivos import (
    PasivoCancelarConChequeRequest,
    PasivoCancelarEfectivoRequest,
    PasivoCancelarRequest,
    PasivoCreate,
)
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)


def create_pasivo(
    db: Session,
    payload: PasivoCreate,
    created_at: datetime | None = None,
) -> Pasivo:
    pasivo = Pasivo(
        acreedor=payload.acreedor.strip(),
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        saldo_pendiente=payload.monto,
        moneda=payload.moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=payload.fecha_vencimiento,
        observaciones=payload.observaciones,
    )
    if created_at is not None:
        pasivo.created_at = created_at
    db.add(pasivo)
    db.commit()
    db.refresh(pasivo)
    return pasivo


def get_pasivo(db: Session, pasivo_id: uuid.UUID) -> Pasivo:
    pasivo = db.get(Pasivo, pasivo_id)
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    return pasivo


def list_pasivos(db: Session, estado: PasivoEstado | None = None) -> list[Pasivo]:
    stmt = select(Pasivo)
    if estado is not None:
        stmt = stmt.where(Pasivo.estado == estado)
    stmt = stmt.order_by(Pasivo.fecha_vencimiento.asc().nulls_last(), Pasivo.created_at.desc())
    return list(db.scalars(stmt).all())


def cancelar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarRequest
) -> Pasivo:
    pasivo = get_pasivo(db, pasivo_id)
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")
    pasivo.estado = PasivoEstado.CANCELADA
    pasivo.saldo_pendiente = Decimal("0.00")
    pasivo.fecha_cancelacion = payload.fecha_cancelacion or hoy_local()
    db.commit()
    db.refresh(pasivo)
    return pasivo


def cancelar_con_efectivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarEfectivoRequest
) -> Pasivo:
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")
    if payload.monto_cobrado > pasivo.saldo_pendiente:
        raise ValidationError(
            f"El monto cobrado ({payload.monto_cobrado}) supera el saldo pendiente "
            f"({pasivo.saldo_pendiente})."
        )

    pasivo.saldo_pendiente = (pasivo.saldo_pendiente - payload.monto_cobrado).quantize(
        Decimal("0.01")
    )
    if pasivo.saldo_pendiente == Decimal("0.00"):
        pasivo.estado = PasivoEstado.CANCELADA
        pasivo.fecha_cancelacion = payload.fecha_cancelacion or hoy_local()

    db.commit()
    db.refresh(pasivo)
    return pasivo


def cancelar_con_cheque(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarConChequeRequest
) -> Pasivo:
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")

    cheque = db.scalar(
        select(Cheque).where(Cheque.nro_cheque == payload.nro_cheque).with_for_update()
    )
    if cheque is None:
        raise NotFoundError(f"Cheque '{payload.nro_cheque}' no encontrado.")
    if cheque.estado != ChequeEstado.EN_CARTERA:
        raise ConflictError(
            f"El cheque '{payload.nro_cheque}' no está en cartera "
            f"(estado: {cheque.estado.value})."
        )

    valor_neto = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    # diferencia > 0: el cheque cubre de más | diferencia < 0: saldo restante
    diferencia = (valor_neto - pasivo.saldo_pendiente).quantize(Decimal("0.01"))

    try:
        cheque.transition_to(
            ChequeEstado.VENDIDO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
        )
        if diferencia >= Decimal("0.00"):
            pasivo.saldo_pendiente = Decimal("0.00")
            pasivo.estado = PasivoEstado.CANCELADA
            pasivo.fecha_cancelacion = payload.fecha_cancelacion or hoy_local()
        else:
            pasivo.saldo_pendiente = (-diferencia).quantize(Decimal("0.01"))

        db.commit()
        db.refresh(pasivo)
        return pasivo
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cancelar la deuda con cheque.") from exc
