from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.models import PrestamoEstado
from app.db.session import get_db
from app.schemas.prestamos import (
    AbonarCapitalRequest,
    CancelarInteresFijoRequest,
    CobrarInteresRequest,
    CuotaCobrarConChequeRequest,
    CuotaCobrarConChequeResponse,
    CuotaCobroRequest,
    CuotaRead,
    CuotasLoteCobrarConChequeRequest,
    CuotasLoteCobrarConChequeResponse,
    CuotasLoteCobrarRequest,
    InteresFijoUpdate,
    PrestamoCreate,
    PrestamoPagoRequest,
    PrestamoRead,
    PrestamoUpdate,
)
from app.services import prestamos as service


router = APIRouter(prefix="/prestamos", tags=["prestamos"])

DbSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PrestamoRead, status_code=201)
def create_prestamo(payload: PrestamoCreate, db: DbSession) -> PrestamoRead:
    return service.create_prestamo(db, payload)


@router.get("", response_model=list[PrestamoRead])
def list_prestamos(
    db: DbSession,
    estado: PrestamoEstado | None = None,
) -> list[PrestamoRead]:
    return service.list_prestamos(db, estado)


@router.get("/{prestamo_id}", response_model=PrestamoRead)
def get_prestamo(prestamo_id: UUID, db: DbSession) -> PrestamoRead:
    return service.get_prestamo(db, prestamo_id)


@router.patch("/{prestamo_id}", response_model=PrestamoRead)
def editar_prestamo(
    prestamo_id: UUID,
    payload: PrestamoUpdate,
    db: DbSession,
) -> PrestamoRead:
    return service.editar_prestamo(db, prestamo_id, payload)


# ── Préstamo a interés fijo (§Interés fijo) ──────────────────────────────────
# Cuatro operaciones propias, porque en esta modalidad el interés y el capital se
# cobran por separado: el interés cada 30 días y el capital cuando el cliente lo
# devuelve. Las rutas van ANTES de `/{prestamo_id}/pagar` solo por orden de
# lectura; no se pisan entre sí.

@router.post("/{prestamo_id}/interes-fijo/cobrar-interes", response_model=PrestamoRead)
def cobrar_interes(
    prestamo_id: UUID,
    payload: CobrarInteresRequest,
    db: DbSession,
) -> PrestamoRead:
    """Cobra el interés del período vigente (y la mora, si se pide)."""
    return service.cobrar_interes(db, prestamo_id, payload)


@router.post("/{prestamo_id}/interes-fijo/abonar-capital", response_model=PrestamoRead)
def abonar_capital(
    prestamo_id: UUID,
    payload: AbonarCapitalRequest,
    db: DbSession,
) -> PrestamoRead:
    """Recibe capital de vuelta, total o parcial. No toca el interés."""
    return service.abonar_capital(db, prestamo_id, payload)


@router.patch("/{prestamo_id}/interes-fijo", response_model=PrestamoRead)
def editar_interes_fijo(
    prestamo_id: UUID,
    payload: InteresFijoUpdate,
    db: DbSession,
) -> PrestamoRead:
    """Renegocia el interés pactado. Rige de los próximos períodos en adelante."""
    return service.editar_interes_fijo(db, prestamo_id, payload)


@router.post("/{prestamo_id}/interes-fijo/cancelar", response_model=PrestamoRead)
def cancelar_interes_fijo(
    prestamo_id: UUID,
    payload: CancelarInteresFijoRequest,
    db: DbSession,
) -> PrestamoRead:
    """Liquida el préstamo: capital pendiente + interés del período vigente."""
    return service.cancelar_interes_fijo(db, prestamo_id, payload)


@router.post("/{prestamo_id}/pagar", response_model=PrestamoRead)
def pagar_prestamo(
    prestamo_id: UUID,
    payload: PrestamoPagoRequest,
    db: DbSession,
) -> PrestamoRead:
    return service.pagar_prestamo(db, prestamo_id, payload)


@router.post("/{prestamo_id}/cuotas/{cuota_id}/cobros", response_model=CuotaRead)
def cobrar_cuota(
    prestamo_id: UUID,
    cuota_id: UUID,
    payload: CuotaCobroRequest,
    db: DbSession,
) -> CuotaRead:
    return service.cobrar_cuota(
        db, prestamo_id, cuota_id, payload.fecha_cobro, payload.cotizacion_stock
    )


@router.post("/{prestamo_id}/cuotas/{cuota_id}/cobrar-con-cheque", response_model=CuotaCobrarConChequeResponse, status_code=201)
def cobrar_cuota_con_cheque(
    prestamo_id: UUID,
    cuota_id: UUID,
    payload: CuotaCobrarConChequeRequest,
    db: DbSession,
) -> CuotaCobrarConChequeResponse:
    cuota, cheque = service.cobrar_cuota_con_cheque(db, prestamo_id, cuota_id, payload)
    return CuotaCobrarConChequeResponse(cuota=cuota, cheque=cheque)


@router.post("/{prestamo_id}/cuotas/cobrar-lote", response_model=list[CuotaRead])
def cobrar_cuotas_lote(
    prestamo_id: UUID,
    payload: CuotasLoteCobrarRequest,
    db: DbSession,
) -> list[CuotaRead]:
    return service.cobrar_cuotas_lote(
        db, prestamo_id, payload.cuota_ids, payload.fecha_cobro, payload.cotizacion_stock
    )


@router.post("/{prestamo_id}/cuotas/cobrar-con-cheque-lote", response_model=CuotasLoteCobrarConChequeResponse, status_code=201)
def cobrar_cuotas_con_cheque_lote(
    prestamo_id: UUID,
    payload: CuotasLoteCobrarConChequeRequest,
    db: DbSession,
) -> CuotasLoteCobrarConChequeResponse:
    cuotas, cheque = service.cobrar_cuotas_con_cheque_lote(db, prestamo_id, payload)
    return CuotasLoteCobrarConChequeResponse(cuotas=cuotas, cheque=cheque)

