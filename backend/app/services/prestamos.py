from __future__ import annotations

import calendar
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Cliente,
    Cuota,
    CuotaEstado,
    FrecuenciaCuotas,
    Prestamo,
    PrestamoEstado,
)
from app.core.fechas import hoy_local
from app.schemas.prestamos import (
    CuotaCobrarConChequeRequest,
    CuotasLoteCobrarConChequeRequest,
    PrestamoCreate,
    PrestamoPagoRequest,
    PrestamoUpdate,
)
from app.services import caja as svc_caja
from app.services.conversion import calcular_reduccion_saldo
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)


def _registrar_cobro_cuota(
    db: Session, prestamo: Prestamo, cuota: Cuota, monto: Decimal
) -> None:
    """Asienta en la caja el ingreso por lo cobrado de una cuota (en la moneda del préstamo).

    `monto` es lo efectivamente cobrado ahora: para una cuota entera es su `monto`,
    pero si venía con un pago parcial previo es solo el restante. No asienta nada si
    `monto` no es positivo (la caja rechaza montos ≤ 0)."""
    if monto <= Decimal("0.00"):
        return
    cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
    svc_caja.registrar(
        db,
        fecha=cuota.fecha_cobro,
        moneda=prestamo.moneda,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_CUOTA,
        monto=monto,
        referencia_tipo="cuota",
        referencia_id=cuota.id,
        detalle=f"Cuota #{cuota.numero_cuota} - {cliente_nombre}",
    )


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

    fecha_inicio = payload.fecha_inicio or hoy_local()
    prestamo = Prestamo(
        cliente_id=payload.cliente_id,
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
        db.flush()
        # Otorgar el préstamo es un egreso de caja: sale el crédito entregado.
        svc_caja.registrar(
            db,
            fecha=fecha_inicio,
            moneda=prestamo.moneda,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.OTORGAMIENTO_PRESTAMO,
            monto=prestamo.credito,
            referencia_tipo="prestamo",
            referencia_id=prestamo.id,
            detalle=f"Préstamo a {cliente.nombre}",
        )
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


def editar_prestamo(
    db: Session, prestamo_id: uuid.UUID, payload: PrestamoUpdate
) -> Prestamo:
    """Corrige la carga de un préstamo (panel) regenerando el cuadro de cuotas.

    Solo se permite si el préstamo está ACTIVO y NINGUNA cuota fue cobrada: editar
    capital/total/cantidad/frecuencia/fecha rehace todas las cuotas y el egreso de
    caja del otorgamiento. Si ya hubo cobros, se rechaza (desincronizaría la caja)."""
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
        .with_for_update()
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    if prestamo.estado != PrestamoEstado.ACTIVO:
        raise ConflictError(
            f"El préstamo está {prestamo.estado.value} y no se puede editar."
        )
    if any(c.estado == CuotaEstado.COBRADA for c in prestamo.cuotas_detalle):
        raise ConflictError(
            "El préstamo ya tiene cuotas cobradas; no se puede editar su carga. "
            "Anulá los cobros o creá un préstamo nuevo."
        )

    data = payload.model_dump(exclude_unset=True)
    credito = data.get("credito", prestamo.credito)
    total = data.get("total_a_cobrar", prestamo.total_a_cobrar)
    cantidad = data.get("cuotas", prestamo.cuotas)
    frecuencia = data.get("frecuencia", prestamo.frecuencia)
    moneda = data.get("moneda", prestamo.moneda)
    fecha_inicio = data.get("fecha_inicio", prestamo.fecha_inicio)
    if total < credito:
        raise ValidationError("El total a cobrar debe ser mayor o igual al capital.")

    prestamo.credito = credito
    prestamo.total_a_cobrar = total
    prestamo.cuotas = cantidad
    prestamo.frecuencia = frecuencia
    prestamo.moneda = moneda
    prestamo.fecha_inicio = fecha_inicio
    prestamo.ganancia = total - credito

    # Regenerar el cuadro de cuotas (borra las viejas vía delete-orphan).
    prestamo.cuotas_detalle.clear()
    db.flush()
    prestamo.cuotas_detalle = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=fecha_inicio,
        cantidad=cantidad,
        frecuencia=frecuencia,
        total_a_cobrar=total,
    )

    try:
        # Rehacer el egreso de caja del otorgamiento (monto/moneda/fecha pueden cambiar).
        svc_caja.borrar_por_referencia(db, "prestamo", prestamo.id)
        cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
        svc_caja.registrar(
            db,
            fecha=fecha_inicio,
            moneda=moneda,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.OTORGAMIENTO_PRESTAMO,
            monto=credito,
            referencia_tipo="prestamo",
            referencia_id=prestamo.id,
            detalle=f"Préstamo a {cliente_nombre}",
        )
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el prestamo.") from exc


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

    # Cobrar la cuota entera salda lo que le falte (puede traer un pago parcial previo).
    restante = (cuota.monto - cuota.monto_pagado).quantize(Decimal("0.01"))
    cuota.monto_pagado = cuota.monto
    cuota.estado = CuotaEstado.COBRADA
    cuota.fecha_cobro = fecha_cobro or hoy_local()

    try:
        db.flush()
        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            _registrar_cobro_cuota(db, prestamo, cuota, restante)
        # Cualquier cuota no cobrada (PENDIENTE o EN_MORA) mantiene vivo el préstamo.
        pendientes_restantes = db.scalar(
            select(func.count()).select_from(Cuota).where(
                Cuota.prestamo_id == prestamo_id,
                Cuota.estado != CuotaEstado.COBRADA,
            )
        )
        if pendientes_restantes == 0 and prestamo is not None:
            prestamo.estado = PrestamoEstado.CANCELADO
        db.commit()
        db.refresh(cuota)
        return cuota
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de la cuota.") from exc


def cobrar_cuota_con_cheque(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_id: uuid.UUID,
    payload: CuotaCobrarConChequeRequest,
) -> tuple[Cuota, Cheque]:
    cuota = db.scalar(
        select(Cuota)
        .where(Cuota.id == cuota_id, Cuota.prestamo_id == prestamo_id)
        .with_for_update()
    )
    if cuota is None:
        raise NotFoundError("Cuota no encontrada.")
    if cuota.estado == CuotaEstado.COBRADA:
        raise ConflictError("La cuota ya fue cobrada.")

    cheque = Cheque(
        nro_cheque=payload.nro_cheque,
        banco=payload.banco,
        monto=payload.monto,
        porcentaje_compra=payload.porcentaje_compra,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        cliente_origen_id=payload.cliente_origen_id,
        estado=ChequeEstado.EN_CARTERA,
    )

    # El cheque entra a cartera y salda la cuota completa (no mueve efectivo en caja).
    cuota.monto_pagado = cuota.monto
    cuota.estado = CuotaEstado.COBRADA
    cuota.fecha_cobro = payload.fecha_cobro or hoy_local()

    try:
        db.add(cheque)
        db.flush()

        pendientes_restantes = db.scalar(
            select(func.count()).select_from(Cuota).where(
                Cuota.prestamo_id == prestamo_id,
                Cuota.estado != CuotaEstado.COBRADA,
            )
        )
        if pendientes_restantes == 0:
            prestamo = db.get(Prestamo, prestamo_id)
            if prestamo is not None:
                prestamo.estado = PrestamoEstado.CANCELADO

        db.commit()
        db.refresh(cuota)
        db.refresh(cheque)
        return cuota, cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número y banco.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc


def cobrar_cuotas_lote(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_ids: list[uuid.UUID],
    fecha_cobro: date | None = None,
) -> list[Cuota]:
    cuotas = list(
        db.scalars(
            select(Cuota)
            .where(Cuota.prestamo_id == prestamo_id, Cuota.id.in_(cuota_ids))
            .with_for_update()
        )
    )
    if len(cuotas) != len(cuota_ids):
        raise NotFoundError("Una o más cuotas no fueron encontradas.")
    for cuota in cuotas:
        if cuota.estado == CuotaEstado.COBRADA:
            raise ConflictError(f"La cuota {cuota.numero_cuota} ya fue cobrada.")

    hoy = fecha_cobro or hoy_local()
    restantes: dict[uuid.UUID, Decimal] = {}
    for cuota in cuotas:
        restantes[cuota.id] = (cuota.monto - cuota.monto_pagado).quantize(Decimal("0.01"))
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = hoy

    try:
        db.flush()
        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            for cuota in cuotas:
                _registrar_cobro_cuota(db, prestamo, cuota, restantes[cuota.id])
        pendientes_restantes = db.scalar(
            select(func.count()).select_from(Cuota).where(
                Cuota.prestamo_id == prestamo_id,
                Cuota.estado != CuotaEstado.COBRADA,
            )
        )
        if pendientes_restantes == 0 and prestamo is not None:
            prestamo.estado = PrestamoEstado.CANCELADO
        db.commit()
        for cuota in cuotas:
            db.refresh(cuota)
        return cuotas
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de las cuotas.") from exc


def cobrar_cuotas_con_cheque_lote(
    db: Session,
    prestamo_id: uuid.UUID,
    payload: CuotasLoteCobrarConChequeRequest,
) -> tuple[list[Cuota], Cheque]:
    cuotas = list(
        db.scalars(
            select(Cuota)
            .where(Cuota.prestamo_id == prestamo_id, Cuota.id.in_(payload.cuota_ids))
            .with_for_update()
        )
    )
    if len(cuotas) != len(payload.cuota_ids):
        raise NotFoundError("Una o más cuotas no fueron encontradas.")
    for cuota in cuotas:
        if cuota.estado == CuotaEstado.COBRADA:
            raise ConflictError(f"La cuota {cuota.numero_cuota} ya fue cobrada.")

    cheque = Cheque(
        nro_cheque=payload.nro_cheque,
        banco=payload.banco,
        monto=payload.monto,
        porcentaje_compra=payload.porcentaje_compra,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        cliente_origen_id=payload.cliente_origen_id,
        estado=ChequeEstado.EN_CARTERA,
    )

    hoy = payload.fecha_cobro or hoy_local()
    for cuota in cuotas:
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = hoy

    try:
        db.add(cheque)
        db.flush()
        pendientes_restantes = db.scalar(
            select(func.count()).select_from(Cuota).where(
                Cuota.prestamo_id == prestamo_id,
                Cuota.estado != CuotaEstado.COBRADA,
            )
        )
        if pendientes_restantes == 0:
            prestamo = db.get(Prestamo, prestamo_id)
            if prestamo is not None:
                prestamo.estado = PrestamoEstado.CANCELADO
        db.commit()
        for cuota in cuotas:
            db.refresh(cuota)
        db.refresh(cheque)
        return cuotas, cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número y banco.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc


def repartir_pago_en_cuotas(
    saldos: list[Decimal], monto: Decimal
) -> list[Decimal]:
    """Reparte `monto` entre cuotas (por su saldo, en orden) llenando cada una.

    `saldos` es el saldo pendiente de cada cuota, ordenado como se quiera imputar
    (la más vieja primero). Devuelve cuánto se aplica a cada cuota, en el mismo
    orden. La suma de lo devuelto es `min(monto, Σ saldos)`: no reparte de más.
    Pura (sin BD): testeable en el estilo de `tests/`."""
    restante = monto
    aplicado: list[Decimal] = []
    for saldo in saldos:
        cuota_saldo = saldo if saldo > Decimal("0.00") else Decimal("0.00")
        aplica = min(restante, cuota_saldo) if restante > Decimal("0.00") else Decimal("0.00")
        aplica = aplica.quantize(Decimal("0.01"))
        aplicado.append(aplica)
        restante = (restante - aplica).quantize(Decimal("0.01"))
    return aplicado


def pagar_prestamo(
    db: Session, prestamo_id: uuid.UUID, payload: PrestamoPagoRequest
) -> Prestamo:
    """Paga un importe libre (parcial o total) contra un préstamo, en efectivo.

    El importe se imputa a las cuotas no saldadas, de la más vieja a la más nueva,
    llenando el `monto_pagado` de cada una (la que se completa pasa a COBRADA). El
    pago puede venir en otra moneda que la del préstamo: la cotización define cuánto
    del préstamo (en su moneda) queda saldado, pero la caja recibe la plata en la
    moneda efectivamente pagada. Cuando no queda ninguna cuota pendiente, el préstamo
    pasa a CANCELADO."""
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
        .with_for_update()
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    if prestamo.estado == PrestamoEstado.CANCELADO:
        raise ConflictError("El préstamo ya está cancelado.")

    pendientes = [
        c for c in prestamo.cuotas_detalle if c.estado != CuotaEstado.COBRADA
    ]
    pendientes.sort(key=lambda c: c.numero_cuota)
    saldo_total = sum(
        ((c.monto - c.monto_pagado) for c in pendientes), Decimal("0.00")
    ).quantize(Decimal("0.01"))
    if saldo_total <= Decimal("0.00"):
        raise ConflictError("El préstamo no tiene saldo pendiente.")

    es_cross = payload.moneda_pago != prestamo.moneda
    # Cuánto del préstamo (en su moneda) salda este pago; valida cotización y tope.
    reduccion = calcular_reduccion_saldo(
        prestamo.moneda,
        saldo_total,
        payload.moneda_pago,
        payload.monto_pagado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    aplicado = repartir_pago_en_cuotas(
        [(c.monto - c.monto_pagado).quantize(Decimal("0.01")) for c in pendientes],
        reduccion,
    )
    for cuota, aplica in zip(pendientes, aplicado):
        if aplica <= Decimal("0.00"):
            continue
        cuota.monto_pagado = (cuota.monto_pagado + aplica).quantize(Decimal("0.01"))
        if cuota.monto_pagado >= cuota.monto:
            cuota.monto_pagado = cuota.monto
            cuota.estado = CuotaEstado.COBRADA
            cuota.fecha_cobro = fecha

    if all(c.estado == CuotaEstado.COBRADA for c in prestamo.cuotas_detalle):
        prestamo.estado = PrestamoEstado.CANCELADO

    # Una sola línea de caja por el efectivo real que entró, en la moneda pagada.
    cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
    detalle = f"Pago préstamo - {cliente_nombre}"
    if es_cross:
        detalle += f" ({reduccion} {prestamo.moneda.value} @ {payload.cotizacion})"
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=payload.moneda_pago,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_CUOTA,
        monto=payload.monto_pagado,
        referencia_tipo="prestamo",
        referencia_id=prestamo.id,
        detalle=detalle,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    try:
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el pago del préstamo.") from exc

