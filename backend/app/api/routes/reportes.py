from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.reportes import CuotaCobradaHistorialItem, ReporteCajaRead
from app.services import reportes as service


router = APIRouter(prefix="/reportes", tags=["reportes"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/caja", response_model=ReporteCajaRead)
def get_reporte_caja(
    db: DbSession,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> ReporteCajaRead:
    return service.get_reporte_caja(db, desde, hasta)


@router.get("/cobros-cuotas", response_model=list[CuotaCobradaHistorialItem])
def get_cobros_cuotas_historial(
    db: DbSession,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> list[CuotaCobradaHistorialItem]:
    return service.get_cobros_cuotas_historial(db, desde, hasta)

