from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Cliente,
    Cheque,
    ChequeEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    Prestamo,
)
from app.schemas.cheques import ChequeCreate, ChequeFiarRequest, ChequeManualTransition
from app.schemas.prestamos import PrestamoCreate
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)
from app.services.prestamos import construir_cuotas


def create_cheque(db: Session, payload: ChequeCreate) -> Cheque:
    cheque = Cheque(
        **payload.model_dump(),
        estado=ChequeEstado.EN_CARTERA,
    )
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
) -> tuple[Cheque, Prestamo]:
    cheque = db.scalar(
        select(Cheque).where(Cheque.nro_cheque == nro_cheque).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if db.get(Cliente, payload.cliente_destino_id) is None:
        raise NotFoundError("Cliente destino no encontrado.")

    prestamo_payload = PrestamoCreate(
        **payload.prestamo.model_dump(),
        cliente_id=payload.cliente_destino_id,
        cheque_origen_nro=nro_cheque,
    )
    fecha_inicio = prestamo_payload.fecha_inicio or date.today()

    prestamo = Prestamo(
        cliente_id=prestamo_payload.cliente_id,
        cheque_origen_nro=nro_cheque,
        credito=prestamo_payload.credito,
        moneda=prestamo_payload.moneda,
        cuotas=prestamo_payload.cuotas,
        frecuencia=prestamo_payload.frecuencia,
        total_a_cobrar=prestamo_payload.total_a_cobrar,
        ganancia=prestamo_payload.total_a_cobrar - prestamo_payload.credito,
        fecha_inicio=fecha_inicio,
    )
    prestamo.cuotas_detalle = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=fecha_inicio,
        cantidad=prestamo_payload.cuotas,
        frecuencia=prestamo_payload.frecuencia,
        total_a_cobrar=prestamo_payload.total_a_cobrar,
    )

    prestamo_id = prestamo.id
    try:
        cheque.transition_to(
            ChequeEstado.FIADO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            cliente_destino_id=payload.cliente_destino_id,
        )
        db.add(prestamo)
        db.commit()
        db.refresh(cheque)
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo fiar el cheque.") from exc

    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
    )
    if prestamo is None:
        raise DatabaseWriteError("No se pudo recuperar el prestamo creado.")
    return cheque, prestamo
