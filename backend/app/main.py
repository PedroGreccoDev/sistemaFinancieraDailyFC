from __future__ import annotations

import logging
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import cheques, clientes, movimientos, prestamos, reportes, webhook
from app.core.config import get_settings
from app.services.exceptions import ServiceError

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


@app.get("/health", tags=["health"])
def health() -> dict[str, str]:
    return {"status": "ok"}


# REST API
app.include_router(clientes.router, prefix=settings.api_v1_prefix)
app.include_router(cheques.router, prefix=settings.api_v1_prefix)
app.include_router(prestamos.router, prefix=settings.api_v1_prefix)
app.include_router(movimientos.router, prefix=settings.api_v1_prefix)
app.include_router(reportes.router, prefix=settings.api_v1_prefix)

# WhatsApp Bot
app.include_router(webhook.router)

# Frontend — solo activo cuando el build de Vite está presente (producción)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))
