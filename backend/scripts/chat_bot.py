"""Conversar con el bot en la terminal, contra una base local.

Los tests unitarios no ven el flujo completo —la conversación, la operación que
queda pendiente, la confirmación—, y probar en producción significa cargarle
operaciones falsas a la financiera. Esto es el bot de verdad: el mismo modelo, el
mismo dispatcher y la misma base; lo único que se reemplaza es el envío por
WhatsApp, que se imprime en pantalla.

Se entra por `webhook.recibir_mensaje` con un payload de WAHA armado a mano —y no
por `_procesar_mensaje`— para que también se ejercite el **dedupe por id**, que es
lo que evita que un mensaje entregado dos veces se cargue dos veces.

    # Conversar
    backend\\.venv\\Scripts\\python.exe scripts/chat_bot.py --db dailyfc_panel

    # Correr un guion (un mensaje por línea; `#` comenta, `>>` espera confirmación)
    backend\\.venv\\Scripts\\python.exe scripts/chat_bot.py --db dailyfc_panel --guion g.txt

`VERBOSE=1` (o `--verbose`) muestra el intent y el veredicto del clasificador, que
es lo que hay que mirar cuando algo sale distinto de lo esperado.

**Cuesta plata**: cada mensaje es una llamada real al modelo.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from pathlib import Path
from typing import Any

_BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_BACKEND))

# La consola de Windows sale en cp1252 y explota con los acentos de las respuestas.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _preparar_entorno(nombre_base: str) -> str:
    """Pisa el entorno ANTES de importar `app`, y aborta si no es local.

    Tres cosas que no son opcionales:

    1. **`DATABASE_URL` va por env var del proceso**, que gana sobre el `.env`
       del repo —donde apunta a la base de producción en Railway—. Sin esto,
       "probar el bot" escribe en la financiera real.
    2. **WAHA y Telegram se fuerzan a vacío/inalcanzable, no con `setdefault`**:
       si esto se corre bajo `railway run`, el entorno ya trae los de producción
       y una prueba le mandaría un WhatsApp a alguien de verdad.
    3. Se hace **antes** de importar `app`: la config se lee una sola vez.
    """
    url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{nombre_base}"
    os.environ["DATABASE_URL"] = url
    os.environ["WAHA_API_URL"] = "http://127.0.0.1:9"
    os.environ["TELEGRAM_BOT_TOKEN"] = ""
    os.environ["TELEGRAM_CHAT_IDS"] = ""
    # Sin esto el filtro de operador rechazaría el número de prueba.
    os.environ["WHATSAPP_OPERATOR_PHONE"] = ""
    os.environ.setdefault("ADMIN_USERNAME", "admin")
    os.environ.setdefault("ADMIN_PASSWORD", "admin1234")
    os.environ.setdefault("SECRET_KEY", "chat-de-prueba")

    from tests.carga.guardas import verificar_destino

    verificar_destino(url)  # revienta si la URL no es local
    return url


_TELEFONO = "5490000000000"


def _payload(texto: str) -> dict[str, Any]:
    """Un evento de WAHA como el que llega de verdad."""
    return {
        "event": "message",
        "payload": {
            "id": f"false_{_TELEFONO}@c.us_{uuid.uuid4().hex[:20].upper()}",
            "from": f"{_TELEFONO}@c.us",
            "fromMe": False,
            "body": texto,
            "type": "chat",
        },
    }


async def _mandar(texto: str, *, payload: dict[str, Any] | None = None) -> list[str]:
    """Mete un mensaje por el webhook real y devuelve lo que el bot contestaría."""
    from fastapi import BackgroundTasks
    from starlette.requests import Request

    from app.api.routes import webhook

    body = json.dumps(payload or _payload(texto)).encode()

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": body, "more_body": False}

    request = Request(
        {"type": "http", "method": "POST", "path": "/webhook/whatsapp", "headers": []},
        receive,
    )
    tareas = BackgroundTasks()
    await webhook.recibir_mensaje(request, tareas)
    # Fuera de FastAPI nadie corre las background tasks: acá se corren a mano.
    await tareas()
    return _RESPUESTAS.pop_todas()


class _Buzon:
    """Junta lo que el bot quiso mandar por WhatsApp."""

    def __init__(self) -> None:
        self._pendientes: list[str] = []

    async def send_text(self, phone: str, text: str, link_preview: bool = False) -> bool:
        self._pendientes.append(text)
        return True

    def pop_todas(self) -> list[str]:
        salida, self._pendientes = self._pendientes, []
        return salida


_RESPUESTAS = _Buzon()


def _confirmar_destino_efectivo() -> str:
    """Vuelve a chequear, ahora contra lo que el backend de verdad va a usar.

    La guarda de arriba mira la URL que este script arma; esta mira la que quedó
    configurada después de cargar el `.env`. Son distintas si algo falla —un
    import de `app` adelantado, un `.env` con precedencia inesperada— y esa
    diferencia es justo la que termina escribiendo en producción.
    """
    from app.core.config import get_settings

    from tests.carga.guardas import verificar_destino

    efectiva = get_settings().database_url
    verificar_destino(efectiva)
    return efectiva


def _interceptar_whatsapp() -> None:
    """Reemplaza el envío real por el buzón, en los dos módulos que lo usan."""
    from app.api.routes import webhook
    from app.services.whatsapp import client as wa_client

    wa_client.send_text = _RESPUESTAS.send_text  # type: ignore[assignment]
    webhook.wa_client = wa_client  # el webhook lo tiene importado como módulo


def _mostrar(respuestas: list[str]) -> None:
    for r in respuestas:
        print(f"\n\033[36m🤖 {r}\033[0m")
    if not respuestas:
        print("\n\033[33m(el bot no contestó nada)\033[0m")


async def _guion(camino: Path) -> None:
    """Corre una lista de mensajes, uno por línea. `#` comenta."""
    for linea in camino.read_text(encoding="utf-8").splitlines():
        texto = linea.strip()
        if not texto or texto.startswith("#"):
            continue
        print(f"\n\033[1m👤 {texto}\033[0m")
        _mostrar(await _mandar(texto))


async def _interactivo() -> None:
    print("Escribí como el operador. Ctrl-C o 'salir' para terminar.\n")
    loop = asyncio.get_running_loop()
    while True:
        try:
            texto = (await loop.run_in_executor(None, input, "👤 ")).strip()
        except (EOFError, KeyboardInterrupt):
            return
        if texto.lower() in {"salir", "exit", "chau"}:
            return
        if not texto:
            continue
        _mostrar(await _mandar(texto))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="dailyfc_bot", help="base local (default: dailyfc_bot)")
    parser.add_argument("--guion", type=Path, help="archivo con un mensaje por línea")
    parser.add_argument("--verbose", action="store_true", help="intent y veredicto del clasificador")
    args = parser.parse_args()

    _preparar_entorno(args.db)

    if args.verbose or os.getenv("VERBOSE"):
        logging.basicConfig(level=logging.INFO, format="\033[90m  %(name)s · %(message)s\033[0m")
        logging.getLogger("httpx").setLevel(logging.WARNING)

    _interceptar_whatsapp()
    print(f"\033[90mBase: {_confirmar_destino_efectivo()}\033[0m")

    # Un solo event loop para toda la sesión: con un `asyncio.run()` por mensaje,
    # el pool del cliente de IA queda atado a un loop ya cerrado y la primera
    # llamada de cada mensaje falla y se reintenta. No rompe nada, pero agrega una
    # demora que el bot real no tiene — y entonces se está midiendo otra cosa.
    asyncio.run(_guion(args.guion) if args.guion else _interactivo())


if __name__ == "__main__":
    main()
