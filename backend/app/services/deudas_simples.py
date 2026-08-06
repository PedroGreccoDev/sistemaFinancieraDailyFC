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
    Cliente,
    DeudaSimple,
    DeudaSimpleEstado,
    Moneda,
)
from app.core.fechas import hoy_local
from app.schemas.cheques import ChequeRead
from app.schemas.deudas_simples import (
    DeudaSimpleCobrarConChequeRequest,
    DeudaSimpleCobrarConChequeResponse,
    DeudaSimpleCreate,
    DeudaSimplePagoRequest,
    DeudaSimpleRead,
    DeudaSimpleUpdate,
)
from app.services import caja as svc_caja
from app.services.conversion import calcular_reduccion_saldo, convertir_a_moneda_deuda
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
)

# referencia_tipo del EGRESO de origen (el alta) y del INGRESO de cada cobro. Se
# distinguen para que la edición pueda resincronizar SOLO el egreso de origen sin
# tocar las líneas de los cobros ya hechos (ambos apuntan al mismo id de deuda).
_CIEN = Decimal("100")

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


def cobrar_con_cheque(
    db: Session,
    deuda_id: uuid.UUID,
    payload: DeudaSimpleCobrarConChequeRequest,
    created_at: datetime | None = None,
) -> DeudaSimpleCobrarConChequeResponse:
    """Cobra una deuda libre recibiendo un cheque del cliente en vez de efectivo.

    El cheque entra a cartera EN_CARTERA a nombre del cliente de la deuda y salda
    por su **valor neto** (`monto × (1 − %compra)`), no por su nominal.

    **No asienta caja**: no entró efectivo. La plata se reconoce recién cuando ese
    cheque se venda o se cobre, igual que en los fiados (§2) y en el cobro de
    cuotas con cheque (§3). Por eso tampoco lleva `referencia_tipo` de cobro.

    Los cheques son siempre en pesos: si la deuda es en USD, el cobro cruza
    monedas y la `cotizacion` imputa cuánto del saldo (en USD) queda saldado.
    """
    deuda = db.scalar(
        select(DeudaSimple).where(DeudaSimple.id == deuda_id).with_for_update()
    )
    if deuda is None:
        raise NotFoundError("Deuda no encontrada.")
    if deuda.estado == DeudaSimpleEstado.CANCELADA:
        raise ConflictError("La deuda ya está cancelada.")

    # Solo choca contra cheques vivos: uno anulado libera su número (migración 0017).
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
        payload.monto_cheque
        * (_CIEN - payload.porcentaje_compra_cheque)
        / _CIEN
    ).quantize(Decimal("0.01"))

    # El cheque vale pesos; si la deuda es en USD hay que convertir para saber
    # cuánto del saldo salda. Se usa `convertir_a_moneda_deuda` y NO
    # `calcular_reduccion_saldo` porque esta última rechaza un pago mayor al
    # saldo: correcto en efectivo, pero acá el valor del cheque es fijo y un
    # cheque "de más" es el caso normal, no un error.
    equivalente = convertir_a_moneda_deuda(
        deuda.moneda, Moneda.ARS, valor_neto, payload.cotizacion
    )
    es_cross = deuda.moneda != Moneda.ARS

    # Diferencia en la moneda de la deuda: > 0 el negocio le queda debiendo al
    # cliente; < 0 el cliente todavía debe el resto.
    diferencia = (equivalente - deuda.saldo_pendiente).quantize(Decimal("0.01"))

    # Se imputa como mucho el saldo: el excedente no puede dejarlo en negativo,
    # se informa como `diferencia` a favor del cliente.
    reduccion = min(equivalente, deuda.saldo_pendiente)

    fecha = payload.fecha_cobro or hoy_local()
    cheque_nuevo = Cheque(
        nro_cheque=payload.nro_cheque_pago,
        banco=payload.banco_pago,
        monto=payload.monto_cheque,
        porcentaje_compra=payload.porcentaje_compra_cheque,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        estado=ChequeEstado.EN_CARTERA,
        ganancia=Decimal("0.00"),
        cliente_origen_id=deuda.cliente_id,
    )
    # Se inserta con db.add() y no con create_cheque(): recibir un cheque como
    # pago NO es comprarlo, así que no corresponde el egreso COMPRA_CHEQUE. Mismo
    # criterio que fiados (§2) y que el cobro de cuotas con cheque (§3).
    if created_at is not None:
        cheque_nuevo.created_at = created_at

    deuda.saldo_pendiente, cancelada = aplicar_cobro(deuda.saldo_pendiente, reduccion)
    if cancelada:
        deuda.estado = DeudaSimpleEstado.CANCELADA
        deuda.fecha_cancelacion = fecha

    if es_cross and deuda.cotizacion_pago is None:
        deuda.cotizacion_pago = payload.cotizacion

    try:
        db.add(cheque_nuevo)
        db.commit()
        db.refresh(deuda)
        db.refresh(cheque_nuevo)
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc

    return DeudaSimpleCobrarConChequeResponse(
        deuda=DeudaSimpleRead.model_validate(deuda),
        cheque_ingresado=ChequeRead.model_validate(cheque_nuevo),
        diferencia=diferencia,
    )
