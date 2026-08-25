"""Rutas del reset de caja — arrancar el libro de cero.

**Borra datos y no se puede deshacer.** Dos pasos obligados y separados: `GET`
muestra qué se llevaría y qué se conserva, `POST` lo ejecuta y exige que el
operador escriba la frase exacta. Un solo endpoint con un flag haría que el
resumen se pudiera saltear, y ese resumen es la única chance de ver que hay algo
cargado que no se esperaba.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.services import reset_caja as service

router = APIRouter(prefix="/reset-caja", tags=["reset-caja"])

DbSession = Annotated[Session, Depends(get_db)]


class ResetCajaRequest(BaseModel):
    operador_id: str = Field(min_length=1, max_length=80)
    # La frase exacta de `service.CONFIRMACION`. Un booleano se manda por
    # accidente desde cualquier cliente HTTP; una frase escrita a mano no.
    confirmacion: str = Field(min_length=1)


class ResetCajaResumenRead(BaseModel):
    movimientos_caja: int
    movimientos_efectivo: int
    ajustes_caja: int
    gastos_operativos: int
    # Cheques que pasan a contar como preexistentes: siguen en cartera, pero su
    # egreso de compra ya no puede resucitar al editarlos.
    cheques_marcados: int
    # Dónde queda la línea: el día anterior, para que lo que se cargue hoy
    # después del reset descuente como cualquier operación normal.
    fecha_corte: date | None = None
    conserva: dict[str, int]


@router.get("", response_model=ResetCajaResumenRead)
def previsualizar_reset(db: DbSession) -> ResetCajaResumenRead:
    """Qué se borraría y qué queda intacto. No toca nada."""
    return ResetCajaResumenRead(**service.previsualizar(db).__dict__)


@router.post("", response_model=ResetCajaResumenRead)
def ejecutar_reset(payload: ResetCajaRequest, db: DbSession) -> ResetCajaResumenRead:
    """Vacía el libro de caja y el stock de dólares. **Irreversible.**

    Lo que el negocio tiene o debe —cheques, deudas de clientes y pasivos— queda
    intacto, y todo eso pasa a contar como preexistente: editarlo después corrige
    el dato sin volver a mover la caja. Lo que se cargue a partir de acá es
    operación normal, aunque sea el mismo día.

    Después hay que cargar la apertura con los cuatro saldos contados.
    """
    resumen = service.ejecutar(
        db, operador_id=payload.operador_id, confirmacion=payload.confirmacion
    )
    return ResetCajaResumenRead(**resumen.__dict__)
