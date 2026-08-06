from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cliente,
    DeudaSimple,
    DeudaSimpleEstado,
)
from app.core.fechas import hoy_local
from app.schemas.deudas_simples import (
    DeudaSimpleCreate,
    DeudaSimplePagoRequest,
    DeudaSimpleUpdate,
)
from app.services import caja as svc_caja
from app.services.conversion import calcular_reduccion_saldo
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
)

# referencia_tipo del EGRESO de origen (el alta) y del INGRESO de cada cobro. Se
# distinguen para que la edición pueda resincronizar SOLO el egreso de origen sin
# tocar las líneas de los cobros ya hechos (ambos apuntan al mismo id de deuda).
_REF_ORIGEN = "deuda_simple"
_REF_COBRO = "deuda_simple_cobro"


def aplicar_cobro(
    saldo_pendiente: Decimal, reduccion: Decimal
) -> tuple[Decimal, bool]:
    """Nuevo saldo y si la deuda quedó cancelada, tras imputar una `reduccion`.

    `reduccion` es cuánto baja el saldo (en la moneda de la deuda); ya viene
    validada y topeada al saldo por `calcular_reduccion_saldo`. Pura (sin BD):
    testeable en el estilo de `tests/`."""
    nuevo = (saldo_pendiente - reduccion).quantize(Decimal("0.01"))
    return nuevo, nuevo == Decimal("0.00")


def get_deuda_simple(db: Session, deuda_id: uuid.UUID) -> DeudaSimple:
    deuda = db.get(DeudaSimple, deuda_id)
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    return deuda


def list_deudas_simples(
    db: Session, estado: DeudaSimpleEstado | None = None
) -> list[DeudaSimple]:
    query = select(DeudaSimple).where(DeudaSimple.anulado_at.is_(None))
    if estado is not None:
        query = query.where(DeudaSimple.estado == estado)
    return list(db.scalars(query.order_by(DeudaSimple.created_at.desc())))


def _registrar_egreso_origen(db: Session, deuda: DeudaSimple, cliente_nombre: str) -> None:
    """Asienta el EGRESO de caja del alta de la deuda (salió la plata)."""
    svc_caja.registrar(
        db,
        fecha=deuda.fecha,
        moneda=deuda.moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.OTORGAMIENTO_DEUDA,
        monto=deuda.monto,
        referencia_tipo=_REF_ORIGEN,
        referencia_id=deuda.id,
        detalle=f"Deuda de {cliente_nombre} - {deuda.concepto}",
    )


def create_deuda_simple(db: Session, payload: DeudaSimpleCreate) -> DeudaSimple:
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    fecha = payload.fecha or hoy_local()
    deuda = DeudaSimple(
        cliente_id=payload.cliente_id,
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        saldo_pendiente=payload.monto,
        moneda=payload.moneda,
        estado=DeudaSimpleEstado.ABIERTA,
        fecha=fecha,
        observaciones=payload.observaciones,
    )

    try:
        db.add(deuda)
        db.flush()
        _registrar_egreso_origen(db, deuda, cliente.nombre)
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear la deuda.") from exc


def editar_deuda_simple(
    db: Session, deuda_id: uuid.UUID, payload: DeudaSimpleUpdate
) -> DeudaSimple:
    """Corrige la carga de una deuda libre (panel).

    `concepto`, `fecha` y `observaciones` se editan siempre. `monto`/`moneda` solo
    si la deuda está ABIERTA y sin cobros parciales (saldo == monto); cambiarlos
    con cobros hechos desincronizaría la caja. Siempre se resincroniza el EGRESO de
    origen (su monto/moneda/fecha pueden cambiar); las líneas de cobro no se tocan."""
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "moneda" in data
    tiene_cobros = deuda.saldo_pendiente != deuda.monto
    if cambia_dinero and (deuda.estado == DeudaSimpleEstado.CANCELADA or tiene_cobros):
        raise ConflictError(
            "La deuda está cancelada o ya tiene cobros parciales; solo se pueden "
            "editar concepto, fecha y observaciones."
        )

    if "concepto" in data:
        deuda.concepto = data["concepto"].strip()
    if "fecha" in data and data["fecha"] is not None:
        deuda.fecha = data["fecha"]
    if "observaciones" in data:
        deuda.observaciones = data["observaciones"]
    if "moneda" in data:
        deuda.moneda = data["moneda"]
    if "monto" in data:
        # Sin cobros parciales (garantizado arriba): el saldo sigue al monto.
        deuda.monto = data["monto"]
        deuda.saldo_pendiente = data["monto"]

    try:
        # Rehacer solo el egreso de origen (monto/moneda/fecha pueden haber cambiado).
        svc_caja.borrar_por_referencia(db, _REF_ORIGEN, deuda.id)
        cliente_nombre = deuda.cliente.nombre if deuda.cliente else "—"
        _registrar_egreso_origen(db, deuda, cliente_nombre)
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar la deuda.") from exc


def cobrar_deuda_simple(
    db: Session, deuda_id: uuid.UUID, payload: DeudaSimplePagoRequest
) -> DeudaSimple:
    """Cobra una deuda libre (total o parcial), en efectivo.

    La caja recibe la plata en la moneda efectivamente cobrada (`moneda_pago`); el
    saldo baja por el equivalente en la moneda de la deuda (vía cotización si el
    cobro cruza monedas). Cuando el saldo llega a 0, la deuda pasa a CANCELADA."""
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    if deuda.estado == DeudaSimpleEstado.CANCELADA:
        raise ConflictError("La deuda ya está cancelada.")

    es_cross = payload.moneda_pago != deuda.moneda
    reduccion = calcular_reduccion_saldo(
        deuda.moneda,
        deuda.saldo_pendiente,
        payload.moneda_pago,
        payload.monto_cobrado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, reduccion)
    if cancelada:
        deuda.estado = DeudaSimpleEstado.CANCELADA
        deuda.fecha_cancelacion = fecha

    # La primera cotización cross-moneda queda como default editable para próximos cobros.
    if es_cross and deuda.cotizacion_pago is None:
        deuda.cotizacion_pago = payload.cotizacion

    cliente_nombre = deuda.cliente.nombre if deuda.cliente else "—"
    detalle = f"Cobro deuda - {cliente_nombre} - {deuda.concepto}"
    if es_cross:
        detalle += f" ({reduccion} {deuda.moneda.value} @ {payload.cotizacion})"

    # Cobrar la deuda hace entrar plata a la caja en la moneda cobrada (incluye parciales).
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=payload.moneda_pago,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_DEUDA,
        monto=payload.monto_cobrado,
        referencia_tipo=_REF_COBRO,
        referencia_id=deuda.id,
        detalle=detalle,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    try:
        db.commit()
        db.refresh(deuda)
        return deuda
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de la deuda.") from exc
