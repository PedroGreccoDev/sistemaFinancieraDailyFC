from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.reportes import ReporteGananciasRead
from app.services import reportes as service


router = APIRouter(prefix="/reportes", tags=["reportes"])

DbSession = Annotated[Session, Depends(get_db)]


@router.get("/ganancias", response_model=ReporteGananciasRead)
def get_reporte_ganancias(
    db: DbSession,
    desde: date = Query(...),
    hasta: date = Query(...),
) -> ReporteGananciasRead:
    return service.get_reporte_ganancias(db, desde, hasta)

