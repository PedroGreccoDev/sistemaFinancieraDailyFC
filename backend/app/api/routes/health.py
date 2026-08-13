"""Endpoints de salud — públicos, sin sesión.

Son **dos endpoints con dos consumidores distintos**, y confundirlos rompe el
deploy:

- `GET /health` — el healthcheck de Railway (`railway.toml`). Tiene que ser
  trivial y devolver 200 mientras el proceso viva: si devolviera error porque
  WAHA está caído, Railway daría el deploy por fallido y reiniciaría el backend
  en loop por un problema que no es suyo.
- `GET /health/deep` — el diagnóstico completo (§services/health) para el
  watchdog externo. Devuelve **503 cuando algo está CAIDO**, así cualquier
  monitor de uptime lo detecta sin leer el cuerpo; el JSON dice qué falló.
"""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services import health as svc_health

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, str]:
    """Liveness: el proceso está vivo y atendiendo. No toca BD ni red."""
    return {"status": "ok"}


@router.get("/health/deep")
async def health_deep(
    token: str | None = Query(default=None, description="Token de acceso (o header X-Health-Token)"),
    x_health_token: str | None = Header(default=None),
) -> JSONResponse:
    """Diagnóstico completo: BD, WAHA, sesión de WhatsApp, webhook y config.

    Protegido con `HEALTH_TOKEN` (query `?token=` o header `X-Health-Token`),
    porque el detalle cuenta cómo está armada la infra. Si la env var no está
    configurada el endpoint queda abierto — cómodo en local, y por eso conviene
    definirla en Railway.
    """
    esperado = get_settings().health_token
    if esperado and token != esperado and x_health_token != esperado:
        raise HTTPException(status_code=401, detail="Token de health inválido")

    diagnostico = await svc_health.diagnosticar()
    codigo = 503 if diagnostico.estado is svc_health.Estado.CAIDO else 200
    return JSONResponse(status_code=codigo, content=diagnostico.to_dict())
