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
from app.schemas.bugs import (
    BugDetalle,
    BugEstadoUpdate,
    BugFrontendCreate,
    BugRead,
    BugResumen,
)
from app.services import bugs, bugs_reporte as service

router = APIRouter(prefix="/bugs", tags=["bugs"])

# Router aparte para lo único público: el buzón donde el navegador deja sus
# errores. Va sin sesión a propósito — el error que más importa del panel es el
# que impide entrar, y ahí todavía no hay token que mandar. Es la misma decisión
# que la foto del cheque (§Chequera Virtual): lo público es lo que tiene que
# funcionar sin sesión, y se acota por otro lado.
public_router = APIRouter(prefix="/bugs", tags=["bugs"])

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


# ── Público: el buzón del navegador ─────────────────────────────────────────

@public_router.post("/frontend", status_code=202)
def reportar_del_navegador(payload: BugFrontendCreate) -> dict[str, str]:
    """Recibe un error que reventó en la pantalla del operador.

    Hasta acá el registro solo veía lo que pasaba en el servidor. Un error de
    JavaScript deja la pantalla en blanco o un botón que no hace nada, y de eso
    no quedaba **ningún** rastro: el operador reintenta, se cansa y sigue a mano.

    Devuelve 202 y nada más. El navegador no necesita el número —no va a
    mostrarlo— y hacerlo esperar la escritura sería cobrarle al operador, que ya
    está mirando una pantalla rota, el tiempo de anotar el error.

    Sobre que sea público: sin sesión no se puede reportar el error de la
    pantalla de login, que es justo el que deja a todos afuera. Lo que llega
    entra acotado por el schema, con `origen=frontend`, y el antiflood del
    registro impide que alguien llene el chat de Telegram repitiendo el POST.
    """
    ubicacion = payload.ubicacion.strip() or "navegador"
    ruta = payload.ruta.strip() or "/"

    bugs.capturar_mensaje(
        origen=bugs.ORIGEN_FRONTEND,
        # El título viaja a Telegram: se arma con la clase y la pantalla, nunca
        # con el mensaje del error, que puede traer datos del negocio.
        titulo=f"Error en la pantalla ({payload.clase}) — {ruta}",
        tipo=f"Frontend:{payload.clase}",
        ubicacion=ubicacion,
        ambito=f"panel:{ruta}",
        detalle=(
            f"{payload.mensaje}\n\n"
            f"Pantalla: {ruta}\n"
            f"Navegador: {payload.navegador}\n\n"
            f"{payload.stack}"
        ),
        contexto={"clase": payload.clase, "ruta": ruta, "navegador": payload.navegador},
    )
    return {"estado": "anotado"}
