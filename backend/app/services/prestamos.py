from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Cliente,
    Cuota,
    CuotaEstado,
    FrecuenciaCuotas,
    Prestamo,
    PrestamoEstado,
)
from app.schemas.prestamos import PrestamoCreate
from app.services.exceptions import ConflictError, DatabaseWriteError, NotFoundError


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def calcular_vencimiento(fecha_inicio: date, frecuencia: FrecuenciaCuotas, numero: int) -> date:
    if frecuencia == FrecuenciaCuotas.DIARIA:
        return fecha_inicio + timedelta(days=numero)
    if frecuencia == FrecuenciaCuotas.SEMANAL:
        return fecha_inicio + timedelta(weeks=numero)
    if frecuencia == FrecuenciaCuotas.QUINCENAL:
        return fecha_inicio + timedelta(days=15 * numero)
    if frecuencia == FrecuenciaCuotas.MENSUAL:
        return _add_months(fecha_inicio, numero)
    if frecuencia == FrecuenciaCuotas.ANUAL:
        return _add_months(fecha_inicio, 12 * numero)
    raise ValueError(f"Frecuencia no soportada: {frecuencia}")


def construir_cuotas(
    *,
    prestamo: Prestamo,
    fecha_inicio: date,
    cantidad: int,
    frecuencia: FrecuenciaCuotas,
    total_a_cobrar: Decimal,
) -> list[Cuota]:
    monto_base = (total_a_cobrar / Decimal(cantidad)).quantize(Decimal("0.01"))
    cuotas: list[Cuota] = []

    for numero in range(1, cantidad + 1):
        monto = (
            total_a_cobrar - (monto_base * Decimal(cantidad - 1))
            if numero == cantidad
            else monto_base
        )
        cuotas.append(
            Cuota(
                prestamo=prestamo,
                numero_cuota=numero,
                fecha_vencimiento=calcular_vencimiento(fecha_inicio, frecuencia, numero),
                monto=monto,
            )
        )

    return cuotas


def create_prestamo(db: Session, payload: PrestamoCreate) -> Prestamo:
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    fecha_inicio = payload.fecha_inicio or date.today()
    prestamo = Prestamo(
        cliente_id=payload.cliente_id,
        cheque_origen_nro=payload.cheque_origen_nro,
        credito=payload.credito,
        moneda=payload.moneda,
        cuotas=payload.cuotas,
        frecuencia=payload.frecuencia,
        total_a_cobrar=payload.total_a_cobrar,
        ganancia=payload.total_a_cobrar - payload.credito,
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=fecha_inicio,
    )
    prestamo.cuotas_detalle = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=fecha_inicio,
        cantidad=payload.cuotas,
        frecuencia=payload.frecuencia,
        total_a_cobrar=payload.total_a_cobrar,
    )

    try:
        db.add(prestamo)
        db.commit()
        db.refresh(prestamo)
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el prestamo.") from exc


def get_prestamo(db: Session, prestamo_id: uuid.UUID) -> Prestamo:
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    return prestamo


def list_prestamos(db: Session, estado: PrestamoEstado | None = None) -> list[Prestamo]:
    query = select(Prestamo).options(selectinload(Prestamo.cuotas_detalle))
    if estado is not None:
        query = query.where(Prestamo.estado == estado)
    return list(db.scalars(query.order_by(Prestamo.created_at.desc())))


def cobrar_cuota(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_id: uuid.UUID,
    fecha_cobro: date | None = None,
) -> Cuota:
    cuota = db.scalar(
        select(Cuota)
        .where(Cuota.id == cuota_id, Cuota.prestamo_id == prestamo_id)
        .with_for_update()
    )
    if cuota is None:
        raise NotFoundError("Cuota no encontrada.")
    if cuota.estado == CuotaEstado.COBRADA:
        raise ConflictError("La cuota ya fue cobrada.")

    cuota.estado = CuotaEstado.COBRADA
    cuota.fecha_cobro = fecha_cobro or date.today()

    try:
        db.flush()
        pendientes_restantes = db.scalar(
            select(func.count()).select_from(Cuota).where(
                Cuota.prestamo_id == prestamo_id,
                Cuota.estado == CuotaEstado.PENDIENTE,
            )
        )
        if pendientes_restantes == 0:
            prestamo = db.get(Prestamo, prestamo_id)
            if prestamo is not None:
                prestamo.estado = PrestamoEstado.CANCELADO
        db.commit()
        db.refresh(cuota)
        return cuota
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de la cuota.") from exc

