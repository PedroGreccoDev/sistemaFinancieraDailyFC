"""Rutas del registro de bugs — mirar qué se rompió y marcarlo resuelto.

Solo lectura y cambio de estado: **los bugs no se dan de alta por acá ni se
borran**. Se anotan solos cuando algo falla (`services/bugs.py`) y se cierran
cuando se arreglan; borrar uno sería perder que existió, y un bug cerrado que
vuelve a ocurrir se reabre solo, que es justamente la información que interesa.

Van bajo `require_admin`: el traceback de un bug muestra las tripas del sistema
y no le sirve de nada al operador que carga cheques.

Ver §Registro de bugs.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.core.auth import AdminUser
from app.db.session import get_db
from app.schemas.bugs import BugDetalle, BugEstadoUpdate, BugRead, BugResumen
from app.services import bugs_reporte as service

router = APIRouter(prefix="/bugs", tags=["bugs"])

DbSession = Annotated[Session, Depends(get_db)]


# ── Las rutas fijas van ANTES de `/{bug_id}` ────────────────────────────────
# Con el orden al revés, `/bugs/resumen` entra por la ruta del id y Postgres
# nunca llega a verse: FastAPI intenta leer "resumen" como entero y devuelve un
# 422 que no dice nada de lo que pasó.

@router.get("/resumen", response_model=BugResumen)
def resumen(
    db: DbSession,
    _: AdminUser,
    sesion_test: Annotated[str | None, Query()] = None,
) -> BugResumen:
    """Cuántos bugs hay y de qué tipo. Es lo que cierra una sesión de testing."""
    return BugResumen(**vars(service.resumir(db, sesion_test=sesion_test)))


@router.get("/export.md", response_class=PlainTextResponse)
def exportar_markdown(db: DbSession, _: AdminUser) -> str:
    """El mismo documento que escribe el script, servido desde el panel.

    Sirve para leerlo sin entrar a la máquina; el archivo versionado del repo lo
    escribe `scripts/exportar_bugs.py`.
    """
    todos = service.listar(db, limite=2000)
    return service.render_markdown(todos, generado_en=datetime.now(timezone.utc))


@router.get("", response_model=list[BugRead])
def listar(
    db: DbSession,
    _: AdminUser,
    estado: Annotated[str | None, Query()] = None,
    origen: Annotated[str | None, Query()] = None,
    sesion_test: Annotated[str | None, Query()] = None,
    limite: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[BugRead]:
    """Los bugs, el que más veces falló primero."""
    return service.listar(
        db, estado=estado, origen=origen, sesion_test=sesion_test, limite=limite
    )


@router.get("/{bug_id}", response_model=BugDetalle)
def obtener(bug_id: int, db: DbSession, _: AdminUser) -> BugDetalle:
    """El bug completo, con su traceback."""
    return service.obtener(db, bug_id)


@router.patch("/{bug_id}", response_model=BugDetalle)
def cambiar_estado(
    bug_id: int, payload: BugEstadoUpdate, db: DbSession, _: AdminUser
) -> BugDetalle:
    return service.cambiar_estado(
        db, bug_id, estado=payload.estado, notas=payload.notas
    )
