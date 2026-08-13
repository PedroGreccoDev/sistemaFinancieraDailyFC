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

import secrets

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.services import health as svc_health

router = APIRouter(tags=["health"])


def _token_ok(esperado: str, recibidos: tuple[str | None, ...]) -> bool:
    """Compara el token en tiempo constante (`compare_digest`).

    Con `!=` el tiempo de respuesta depende de cuántos caracteres coinciden, y
    eso alcanza para adivinar el token a fuerza de requests.
    """
    return any(r is not None and secrets.compare_digest(r, esperado) for r in recibidos)


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

    **El token decide cuánto se cuenta, no si se responde.** Con `HEALTH_TOKEN`
    válido devuelve el detalle de cada pieza (que es lo que hace útil la
    alerta); sin token válido —o con la env var sin configurar— devuelve el
    mismo estado pero **sin los detalles**, que cuentan a qué URL apunta el
    webhook y qué host de Postgres no contesta.

    Así el olvido de configurar `HEALTH_TOKEN` no abre la infra a cualquiera,
    y a la vez un monitor de uptime sin token sigue viendo el 503.

    El header `X-Health-Token` es preferible a `?token=`: los query params
    quedan escritos en los access logs de proxies y CDNs.
    """
    esperado = get_settings().health_token
    detallado = bool(esperado) and _token_ok(esperado, (x_health_token, token))

    if esperado and not detallado and (token is not None or x_health_token is not None):
        # Mandó un token y está mal: eso es un error, no una consulta anónima.
        raise HTTPException(status_code=401, detail="Token de health inválido")

    diagnostico = await svc_health.diagnosticar()
    codigo = 503 if diagnostico.estado is svc_health.Estado.CAIDO else 200
    return JSONResponse(status_code=codigo, content=diagnostico.to_dict(detallado=detallado))
