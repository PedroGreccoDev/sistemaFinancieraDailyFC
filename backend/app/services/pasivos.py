from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    Moneda,
    Pasivo,
    PasivoEstado,
)
from app.core.fechas import hoy_local
from app.services import caja as svc_caja
from app.schemas.pasivos import (
    PasivoCancelarConChequeRequest,
    PasivoCancelarEfectivoRequest,
    PasivoCancelarRequest,
    PasivoCreate,
    PasivoUpdate,
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


def editar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoUpdate
) -> Pasivo:
    """Corrige la carga de una deuda (panel).

    `acreedor`, `concepto`, `fecha_vencimiento` y `observaciones` se editan siempre.
    `monto`/`moneda` solo si la deuda está PENDIENTE y sin pagos parciales (cambiarlos
    con pagos hechos desincronizaría la caja); al editar el monto se recalcula el saldo.
    El alta de un pasivo no genera línea de caja, así que no hay nada que resincronizar."""
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "moneda" in data
    tiene_pagos = pasivo.saldo_pendiente != pasivo.monto
    if cambia_dinero and (pasivo.estado == PasivoEstado.CANCELADA or tiene_pagos):
        raise ConflictError(
            "La deuda está cancelada o ya tiene pagos parciales; solo se pueden editar "
            "acreedor, concepto, vencimiento y observaciones."
        )

    if "acreedor" in data:
        pasivo.acreedor = data["acreedor"].strip()
    if "concepto" in data:
        pasivo.concepto = data["concepto"].strip()
    if "fecha_vencimiento" in data:
        pasivo.fecha_vencimiento = data["fecha_vencimiento"]
    if "observaciones" in data:
        pasivo.observaciones = data["observaciones"]
    if "moneda" in data:
        pasivo.moneda = data["moneda"]
    if "monto" in data:
        # Sin pagos parciales (garantizado arriba): el saldo sigue al monto.
        pasivo.monto = data["monto"]
        pasivo.saldo_pendiente = data["monto"]

    db.commit()
    db.refresh(pasivo)
    return pasivo


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

    # Pagar la deuda en efectivo es un egreso de caja en la moneda del pasivo (incluye parciales).
    svc_caja.registrar(
        db,
        fecha=payload.fecha_cancelacion or hoy_local(),
        moneda=pasivo.moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.PAGO_PASIVO,
        monto=payload.monto_cobrado,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=f"Pago deuda a {pasivo.acreedor}",
    )

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
        select(Cheque).where(Cheque.id == payload.cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError(f"Cheque '{payload.cheque_id}' no encontrado.")
    if cheque.estado != ChequeEstado.EN_CARTERA:
        raise ConflictError(
            f"El cheque Nº {cheque.nro_cheque} no está en cartera "
            f"(estado: {cheque.estado.value})."
        )

    valor_neto = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    # diferencia > 0: el cheque cubre de más | diferencia < 0: saldo restante
    diferencia = (valor_neto - pasivo.saldo_pendiente).quantize(Decimal("0.01"))

    # Si el cheque cubre de más, el operador DEBE indicar qué hacer con el vuelto.
    if diferencia > Decimal("0.00") and payload.vuelto_modo is None:
        raise ValidationError(
            "El cheque cubre de más. Indicá qué hacer con el vuelto: "
            "'SALDAR_EFECTIVO' (le pagás la diferencia) o 'QUEDA_DEBIENDO' "
            "(queda como deuda a favor del cliente)."
        )

    fecha_canc = payload.fecha_cancelacion or hoy_local()
    try:
        # Pagar la deuda entregando un cheque de cartera NO mueve efectivo (el desembolso
        # ya ocurrió al comprar el cheque); por eso pasa por el modelo, no por svc_cheques.
        cheque.transition_to(
            ChequeEstado.VENDIDO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
        )
        if diferencia >= Decimal("0.00"):
            pasivo.saldo_pendiente = Decimal("0.00")
            pasivo.estado = PasivoEstado.CANCELADA
            pasivo.fecha_cancelacion = fecha_canc
            if diferencia > Decimal("0.00"):
                _aplicar_vuelto(db, cheque, payload.vuelto_modo, diferencia, fecha_canc)
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


def _aplicar_vuelto(
    db: Session,
    cheque: Cheque,
    modo: str | None,
    diferencia: Decimal,
    fecha: date,
) -> None:
    """Resuelve el vuelto cuando un cheque cubre de más un pasivo (diferencia > 0).

    El vuelto es en ARS (el cheque es un instrumento en pesos).
    """
    cliente = cheque.cliente_origen
    cliente_nombre = cliente.nombre if cliente else "cliente"

    if modo == "SALDAR_EFECTIVO":
        # Le pagás el vuelto en efectivo/transferencia: egreso de caja ARS.
        svc_caja.registrar(
            db,
            fecha=fecha,
            moneda=Moneda.ARS,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.VUELTO_PASIVO,
            monto=diferencia,
            referencia_tipo="cheque",
            referencia_id=cheque.id,
            detalle=f"Vuelto en efectivo a {cliente_nombre} (cheque Nº {cheque.nro_cheque})",
        )
    else:  # QUEDA_DEBIENDO
        # Quedás debiendo: se crea un pasivo a favor del cliente (sin movimiento de caja).
        db.add(
            Pasivo(
                acreedor=cliente_nombre,
                concepto=f"Vuelto cheque Nº {cheque.nro_cheque}",
                monto=diferencia,
                saldo_pendiente=diferencia,
                moneda=Moneda.ARS,
                estado=PasivoEstado.PENDIENTE,
            )
        )
