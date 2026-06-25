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
    Cliente,
    Cheque,
    ChequeEstado,
    Fiado,
    FiadoEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    Moneda,
)
from app.core.fechas import fecha_local, hoy_local
from app.schemas.cheques import ChequeCreate, ChequeFiarRequest, ChequeManualTransition
from app.services import caja as svc_caja
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CIEN = Decimal("100")


def create_cheque(
    db: Session,
    payload: ChequeCreate,
    created_at: datetime | None = None,
    foto: bytes | None = None,
    foto_mime: str | None = None,
) -> Cheque:
    cheque = Cheque(
        **payload.model_dump(),
        estado=ChequeEstado.EN_CARTERA,
        foto=foto,
        foto_mime=foto_mime,
    )
    if created_at is not None:
        cheque.created_at = created_at
    try:
        db.add(cheque)
        db.flush()
        # Comprar el cheque saca plata de la caja ARS: lo pagado = monto·(1−%compra).
        pagado = (cheque.monto * (_CIEN - cheque.porcentaje_compra) / _CIEN).quantize(Decimal("0.01"))
        if pagado > 0:
            banco_txt = f" — {cheque.banco}" if cheque.banco else ""
            svc_caja.registrar(
                db, fecha=fecha_local(created_at), moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.COMPRA_CHEQUE, monto=pagado,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=f"Compra cheque Nº {cheque.nro_cheque}{banco_txt}",
            )
        db.commit()
        db.refresh(cheque)
        return cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(_msg_duplicado(db, payload.nro_cheque, payload.banco)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el cheque.") from exc


def _msg_duplicado(db: Session, nro_cheque: str, banco: str | None) -> str:
    """Mensaje informativo cuando choca la unicidad (banco, nro_cheque).

    En vez de un escueto "ya existe", devolvemos los datos del cheque que ya estaba
    cargado para que el operador distinga un duplicado real de un cheque homónimo de
    otro banco o de data vieja."""
    existente = db.scalar(
        select(Cheque).where(Cheque.nro_cheque == nro_cheque, Cheque.banco == banco)
    )
    if existente is None:
        return "Ya existe un cheque con ese número y banco."
    banco_txt = f" del banco {existente.banco}" if existente.banco else ""
    fecha = existente.created_at.strftime("%d/%m/%y") if existente.created_at else "—"
    return (
        f"Ya existe el cheque Nº {existente.nro_cheque}{banco_txt}: "
        f"${existente.monto:,.2f}, estado {existente.estado.value}, cargado el {fecha}. "
        "Si es otro cheque distinto, indicá el banco para diferenciarlo."
    )


def get_cheque(db: Session, cheque_id: uuid.UUID) -> Cheque:
    cheque = db.get(Cheque, cheque_id)
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    return cheque


def resolve_cheque(db: Session, nro: str, banco: str | None = None) -> Cheque:
    """Resuelve una referencia a un cheque (número, posiblemente parcial) a una fila.

    El operador suele nombrar el cheque por su número (a veces solo los últimos
    dígitos). Como el número ya NO es único entre bancos, esta función:
      1. Busca por número exacto; si no hay, por sufijo ("el 681" → "…03789681").
      2. Si se indicó banco, filtra por él.
      3. Si queda exactamente uno, lo devuelve; si hay varios, pide desambiguar por banco.
    """
    nro = (nro or "").strip()
    if not nro:
        raise ValidationError("Indicá el número de cheque.")

    matches = list(db.scalars(select(Cheque).where(Cheque.nro_cheque == nro)))
    if not matches:
        matches = list(db.scalars(select(Cheque).where(Cheque.nro_cheque.endswith(nro))))
    if not matches:
        raise NotFoundError(f"No encontré ningún cheque con el número '{nro}'.")

    if banco:
        filtrados = [c for c in matches if c.banco and banco.lower() in c.banco.lower()]
        if filtrados:
            matches = filtrados

    if len(matches) == 1:
        return matches[0]

    detalle = ", ".join(f"{c.nro_cheque} ({c.banco or 'sin banco'})" for c in matches[:5])
    raise ValidationError(
        f"Hay {len(matches)} cheques con ese número: {detalle}. "
        "Indicá el banco para distinguirlos."
    )


def get_cheque_foto(db: Session, cheque_id: uuid.UUID) -> tuple[bytes, str]:
    """Devuelve (bytes, mime) de la foto del cheque.

    La columna `foto` es diferida: este acceso dispara la carga del binario solo
    para este cheque puntual (no para los listados).
    """
    cheque = db.get(Cheque, cheque_id)
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if cheque.foto is None:
        raise NotFoundError("El cheque no tiene foto.")
    return cheque.foto, cheque.foto_mime or "image/jpeg"


def list_cheques(db: Session, estado: ChequeEstado | None = None) -> list[Cheque]:
    query = select(Cheque)
    if estado is not None:
        query = query.where(Cheque.estado == estado)
    return list(db.scalars(query.order_by(Cheque.created_at.desc())))


def transition_cheque(
    db: Session,
    cheque_id: uuid.UUID,
    payload: ChequeManualTransition,
    event_at: datetime | None = None,
) -> Cheque:
    if payload.target_state == ChequeEstado.FIADO:
        raise ValidationError(
            "Para fiar un cheque use /cheques/{cheque_id}/fiar, "
            "que crea la deuda asociada en la misma transaccion."
        )

    cheque = db.scalar(
        select(Cheque).where(Cheque.id == cheque_id).with_for_update()
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
        # Vender o cobrar el cheque hace entrar plata a la caja ARS.
        #  VENDIDO → lo recibido = monto·(1−%venta);  COBRADO → el nominal completo.
        ingreso: Decimal | None = None
        if payload.target_state == ChequeEstado.VENDIDO:
            ingreso = (cheque.monto * (_CIEN - cheque.porcentaje_venta) / _CIEN).quantize(Decimal("0.01"))
            categoria = CajaCategoria.VENTA_CHEQUE
            accion = "Venta"
        elif payload.target_state == ChequeEstado.COBRADO:
            ingreso = cheque.monto.quantize(Decimal("0.01"))
            categoria = CajaCategoria.COBRO_CHEQUE
            accion = "Cobro"
        if ingreso is not None and ingreso > 0:
            svc_caja.registrar(
                db, fecha=fecha_local(event_at), moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
                categoria=categoria, monto=ingreso,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=f"{accion} cheque Nº {cheque.nro_cheque}",
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
    cheque_id: uuid.UUID,
    payload: ChequeFiarRequest,
    fecha_fiado: date | None = None,
    event_at: datetime | None = None,
) -> tuple[Cheque, Fiado]:
    cheque = db.scalar(
        select(Cheque).where(Cheque.id == cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if db.get(Cliente, payload.cliente_destino_id) is None:
        raise NotFoundError("Cliente destino no encontrado.")

    saldo_pendiente = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    fiado = Fiado(
        cheque_id=cheque.id,
        cliente_id=payload.cliente_destino_id,
        monto_original=cheque.monto,
        porcentaje_venta=payload.porcentaje_venta,
        saldo_pendiente=saldo_pendiente,
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=fecha_fiado or hoy_local(),
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
