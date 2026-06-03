from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import cheques, clientes, movimientos, prestamos, reportes, webhook
from app.core.config import get_settings
from app.services.exceptions import ServiceError


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
