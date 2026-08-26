from __future__ import annotations

from decimal import Decimal
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import Moneda, PasivoEstado
from app.db.session import get_db
from app.schemas.pasivos import (
    CancelarAcreedorChequeRequest,
    PagoAcreedorRequest,
    PagoAcreedorResponse,
    PasivoCancelarConChequeRequest,
    PasivoCreate,
    PasivoImputadoRead,
    PasivoPagoRequest,
    PasivoRead,
    PasivoUpdate,
)
from app.services import cheques as svc_cheques
from app.services import pasivos as service

router = APIRouter(prefix="/pasivos", tags=["pasivos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PasivoRead, status_code=201)
def create_pasivo(payload: PasivoCreate, db: DbSession) -> PasivoRead:
    return service.create_pasivo(db, payload)


@router.get("", response_model=list[PasivoRead])
def list_pasivos(
    db: DbSession,
    estado: PasivoEstado | None = None,
) -> list[PasivoRead]:
    return service.list_pasivos(db, estado=estado)


def _respuesta_acreedor(
    resultado: service.PagoAcreedorResult, moneda_deuda: Moneda
) -> PagoAcreedorResponse:
    """Arma la respuesta HTTP a partir del resultado del servicio.

    El servicio devuelve los modelos vivos (los usa el bot para redactar su
    mensaje); acá se recorta a lo que el panel necesita mostrar."""
    return PagoAcreedorResponse(
        acreedor=resultado.acreedor,
        moneda_deuda=moneda_deuda,
        imputaciones=[
            PasivoImputadoRead(
                id=imp.pasivo.id,
                concepto=imp.pasivo.concepto,
                imputado=imp.imputado,
                saldo_restante=imp.pasivo.saldo_pendiente,
                cancelo=imp.cancelo,
            )
            for imp in resultado.imputaciones
        ],
        imputado=sum((imp.imputado for imp in resultado.imputaciones), Decimal("0.00")),
        saldo_restante=resultado.saldo_restante,
        cancelados=resultado.cancelados,
    )


@router.post("/acreedores/pagar", response_model=PagoAcreedorResponse)
def pagar_a_acreedor(
    payload: PagoAcreedorRequest, db: DbSession
) -> PagoAcreedorResponse:
    """Paga todas las deudas con un acreedor, de la más vieja a la más nueva.

    Es la misma función que usa el bot: el reparto no depende de por dónde entró
    la orden."""
    resultado = service.pagar_a_acreedor(
        db,
        acreedor=payload.acreedor,
        moneda_deuda=payload.moneda_deuda,
        monto_pagado=payload.monto_pagado,
        moneda_pago=payload.moneda_pago,
        medio_pago=payload.medio_pago,
        cotizacion=payload.cotizacion,
        fecha=payload.fecha,
    )
    return _respuesta_acreedor(resultado, payload.moneda_deuda)


@router.post("/acreedores/cancelar-con-cheque", response_model=PagoAcreedorResponse)
def cancelar_a_acreedor_con_cheque(
    payload: CancelarAcreedorChequeRequest, db: DbSession
) -> PagoAcreedorResponse:
    """Entrega un cheque de cartera contra todas las deudas en pesos del acreedor.

    Un cheque es un instrumento en pesos: no hay con qué imputarlo a una deuda en
    dólares sin una cotización que nadie dictó."""
    cheque = svc_cheques.get_cheque(db, payload.cheque_id)
    resultado = service.cancelar_a_acreedor_con_cheque(
        db,
        acreedor=payload.acreedor,
        cheque=cheque,
        porcentaje_venta=payload.porcentaje_venta,
        operador_id=payload.operador_id,
        motivo=payload.motivo,
        fecha=payload.fecha,
        vuelto_modo=payload.vuelto_modo,
    )
    return _respuesta_acreedor(resultado, Moneda.ARS)


@router.get("/{pasivo_id}", response_model=PasivoRead)
def get_pasivo(pasivo_id: UUID, db: DbSession) -> PasivoRead:
    return service.get_pasivo(db, pasivo_id)


@router.patch("/{pasivo_id}", response_model=PasivoRead)
def editar_pasivo(pasivo_id: UUID, payload: PasivoUpdate, db: DbSession) -> PasivoRead:
    return service.editar_pasivo(db, pasivo_id, payload)


@router.post("/{pasivo_id}/pagar", response_model=PasivoRead)
def pagar_pasivo(
    pasivo_id: UUID,
    payload: PasivoPagoRequest,
    db: DbSession,
) -> PasivoRead:
    return service.pagar_pasivo(db, pasivo_id, payload)


@router.post("/{pasivo_id}/cancelar-con-cheque", response_model=PasivoRead)
def cancelar_pasivo_con_cheque(
    pasivo_id: UUID,
    payload: PasivoCancelarConChequeRequest,
    db: DbSession,
) -> PasivoRead:
    return service.cancelar_con_cheque(db, pasivo_id, payload)
