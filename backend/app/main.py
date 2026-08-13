from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import ajustes_caja, anulacion, apertura, auth, backup, cheques, clientes, deudas_simples, fiados, gastos_operativos, health, movimientos, pasivos, prestamos, reportes, webhook
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services import monitor
from app.services.exceptions import ServiceError
from app.services.usuarios import bootstrap_admin

STATIC_DIR = Path(__file__).parent.parent / "static"


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)

settings = get_settings()

app = FastAPI(title=settings.app_name)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ServiceError)
async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.on_event("startup")
def _startup() -> None:
    # Crea el admin raíz desde las env vars si no existe (idempotente). Si la BD
    # todavía no está migrada (tabla usuarios ausente), logueamos y seguimos para
    # no tumbar el arranque del proceso web.
    db = SessionLocal()
    try:
        bootstrap_admin(db)
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("Bootstrap de admin omitido: %s", exc)
    finally:
        db.close()

    # Vigilancia de salud en background (WAHA, sesión de WhatsApp, BD) con
    # alerta por Telegram. No corre si falta la config de Telegram, y si algo
    # sale mal al arrancarla no puede tumbar el proceso web: el monitor existe
    # para avisar de caídas, no para causarlas.
    try:
        monitor.iniciar()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("No se pudo iniciar el monitor de salud: %s", exc)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await monitor.detener()


# Salud — público: /health (liveness de Railway) y /health/deep (watchdog externo)
app.include_router(health.router)

# Autenticación (login, recuperación, invitaciones, gestión de usuarios) — público
app.include_router(auth.router, prefix=settings.api_v1_prefix)

# Foto de cheque — pública: se sirve por UUID no-adivinable para poder usarse en
# <img src> directos del panel (que no pueden mandar el header Authorization).
app.include_router(cheques.public_router, prefix=settings.api_v1_prefix)

# REST API de negocio — protegida: requiere sesión válida (Bearer token)
_auth = [Depends(get_current_user)]
app.include_router(clientes.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(cheques.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(prestamos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(movimientos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(reportes.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(pasivos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(fiados.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(deudas_simples.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(gastos_operativos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(ajustes_caja.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(anulacion.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(apertura.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(backup.router, prefix=settings.api_v1_prefix, dependencies=_auth)

# WhatsApp Bot — público (mantiene su propio control por número de teléfono)
app.include_router(webhook.router)

# Frontend — solo activo cuando el build de Vite está presente (producción)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))
