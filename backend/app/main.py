from __future__ import annotations

import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import ajustes_caja, anulacion, apertura, auth, backup, bugs as rutas_bugs, cheques, clientes, compensaciones, deudas_simples, deudores, fiados, gastos_operativos, health, movimientos, pasivos, prestamos, reportes, reset_caja, traspasos, webhook
from app.core.auth import get_current_user
from app.core.config import get_settings
from app.db.session import SessionLocal
from app.services import bugs, monitor
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


def _ambito(request: Request) -> str:
    """Por dónde entró el request, con la ruta sin los identificadores.

    Se prefiere la plantilla de la ruta (`/clientes/{cliente_id}`) sobre la URL
    real: así todos los errores de ese endpoint son un solo bug y no uno por
    cliente. Si la excepción saltó antes de resolverse la ruta, queda la URL y
    `bugs.normalizar_ambito` le saca los IDs igual.
    """
    ruta = getattr(request.scope.get("route"), "path", None) or request.url.path
    return f"{request.method} {ruta}"


@app.exception_handler(ServiceError)
async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
    # Un ServiceError de 4xx es el negocio diciendo que no ("el cheque ya está
    # vendido"): operación normal, no bug. Uno de 5xx —DatabaseWriteError— es el
    # sistema fallando, y ese sí tiene que quedar anotado y sonar.
    if exc.status_code >= 500:
        bugs.capturar(exc, origen=bugs.ORIGEN_PANEL, ambito=_ambito(request))
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Toda excepción no controlada del panel: la anota y le pone número.

    Este handler es la razón de ser del registro de bugs. Hasta que existió, un
    500 de cualquier endpoint moría en los logs de Railway: el operador veía una
    pantalla rota, seguía trabajando como podía, y del lado técnico nadie se
    enteraba hasta que algo no cerraba. Ahora suena en el momento, con un número
    para buscarlo en `docs/BUGS.md`.

    Del lado del cliente no cambia nada: sigue siendo un 500 genérico. El
    mensaje de la excepción no se devuelve —arrastra SQL con datos del negocio—
    y queda en la tabla.
    """
    bugs.capturar(exc, origen=bugs.ORIGEN_PANEL, ambito=_ambito(request))
    return JSONResponse(
        status_code=500,
        content={"detail": "Ocurrió un error inesperado. Ya quedó registrado."},
    )


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

    # Registro de bugs: el drenador que escribe la tabla y avisa, y el enganche
    # al logging que convierte en bug todo `logger.error` del proceso —incluidos
    # los de los `except Exception` que loguean y siguen—. Como el monitor, si
    # algo falla al arrancarlo no puede tumbar el proceso web: existe para que
    # los errores se vean, no para causarlos.
    try:
        bugs.iniciar()
        bugs.instalar_captura_de_logs()
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).error("No se pudo iniciar el registro de bugs: %s", exc)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await monitor.detener()
    # Después del monitor: si al detenerse dejó algún error encolado, esta
    # última pasada lo escribe antes de que el proceso se vaya.
    await bugs.detener()


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
app.include_router(deudores.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(compensaciones.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(gastos_operativos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(ajustes_caja.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(traspasos.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(reset_caja.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(anulacion.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(apertura.router, prefix=settings.api_v1_prefix, dependencies=_auth)
app.include_router(backup.router, prefix=settings.api_v1_prefix, dependencies=_auth)
# Registro de bugs — cada ruta exige además admin (§Registro de bugs): el
# traceback muestra las tripas del sistema y no le sirve al operador.
app.include_router(rutas_bugs.router, prefix=settings.api_v1_prefix, dependencies=_auth)

# WhatsApp Bot — público (mantiene su propio control por número de teléfono)
app.include_router(webhook.router)

# Frontend — solo activo cuando el build de Vite está presente (producción)
if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(STATIC_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa_fallback(full_path: str) -> FileResponse:
        return FileResponse(str(STATIC_DIR / "index.html"))
