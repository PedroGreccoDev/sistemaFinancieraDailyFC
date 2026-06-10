from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    Cliente,
    Cheque,
    ChequeEstado,
    Fiado,
    FiadoEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
)
from app.schemas.cheques import ChequeCreate, ChequeFiarRequest, ChequeManualTransition
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)


def create_cheque(
    db: Session,
    payload: ChequeCreate,
    created_at: datetime | None = None,
) -> Cheque:
    cheque = Cheque(
        **payload.model_dump(),
        estado=ChequeEstado.EN_CARTERA,
    )
    if created_at is not None:
        cheque.created_at = created_at
    try:
        db.add(cheque)
        db.commit()
        db.refresh(cheque)
        return cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese numero.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el cheque.") from exc


def get_cheque(db: Session, nro_cheque: str) -> Cheque:
    cheque = db.get(Cheque, nro_cheque)
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    return cheque


def list_cheques(db: Session, estado: ChequeEstado | None = None) -> list[Cheque]:
    query = select(Cheque)
    if estado is not None:
        query = query.where(Cheque.estado == estado)
    return list(db.scalars(query.order_by(Cheque.created_at.desc())))


def transition_cheque(
    db: Session,
    nro_cheque: str,
    payload: ChequeManualTransition,
    event_at: datetime | None = None,
) -> Cheque:
    if payload.target_state == ChequeEstado.FIADO:
        raise ValidationError(
            "Para fiar un cheque use /cheques/{nro_cheque}/fiar, "
            "que crea la deuda asociada en la misma transaccion."
        )

    cheque = db.scalar(
        select(Cheque).where(Cheque.nro_cheque == nro_cheque).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")

    try:
        cheque.transition_to(
            payload.target_state,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
            cliente_destino_id=payload.cliente_destino_id,
            event_at=event_at,
        )
        db.commit()
        db.refresh(cheque)
        return cheque
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cambiar el estado del cheque.") from exc


def fiar_cheque(
    db: Session,
    nro_cheque: str,
    payload: ChequeFiarRequest,
    fecha_fiado: date | None = None,
    event_at: datetime | None = None,
) -> tuple[Cheque, Fiado]:
    cheque = db.scalar(
        select(Cheque).where(Cheque.nro_cheque == nro_cheque).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if db.get(Cliente, payload.cliente_destino_id) is None:
        raise NotFoundError("Cliente destino no encontrado.")

    saldo_pendiente = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    fiado = Fiado(
        cheque_nro=nro_cheque,
        cliente_id=payload.cliente_destino_id,
        monto_original=cheque.monto,
        porcentaje_venta=payload.porcentaje_venta,
        saldo_pendiente=saldo_pendiente,
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=fecha_fiado or date.today(),
    )

    try:
        cheque.transition_to(
            ChequeEstado.FIADO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
            cliente_destino_id=payload.cliente_destino_id,
            event_at=event_at,
        )
        db.add(fiado)
        db.commit()
        db.refresh(cheque)
        db.refresh(fiado)
        return cheque, fiado
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo fiar el cheque.") from exc
