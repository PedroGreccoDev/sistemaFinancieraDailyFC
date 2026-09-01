"""Smoke end-to-end de la carga de e-cheq: de la foto a la fila en la base.

`probar_ocr.py` verifica que el modelo LEA bien la captura. Esto verifica lo que
pasa después: que el dispatcher cargue el cheque, que la plata salga de la caja
por el monto correcto, y que el comprobante que recibe el operador diga lo que
tiene que decir. Son dos mitades del mismo camino y hasta acá solo estaba probada
la primera.

Corre contra una base LOCAL que crea y migra al momento, nunca contra producción:
sin ese recaudo, "probar" sería cargarle cheques falsos a la financiera real.

**Cuesta plata:** una llamada real a la API por imagen.

Uso (desde `backend/`):
    .venv\\Scripts\\python.exe scripts/smoke_echeq.py <carpeta-de-capturas>
    .venv\\Scripts\\python.exe scripts/smoke_echeq.py <carpeta> --conservar

La base se llama `dailyfc_smoke_echeq` y se borra al terminar salvo que se pase
`--conservar` para poder mirarla con psql.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_BASE = "dailyfc_smoke_echeq"
_PG = Path(r"C:\Program Files\PostgreSQL\17\bin")
_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{_BASE}"

# ── Guardas de entorno, ANTES de importar `app` ──────────────────────────────
# Asignación directa y no setdefault: el .env del repo apunta a producción y bajo
# `railway run` el entorno ya trae WAHA y Telegram reales. Un default no los
# pisaría y una prueba podría escribir en la financiera o mandar un WhatsApp.
os.environ["DATABASE_URL"] = _URL
os.environ["WAHA_API_URL"] = "http://127.0.0.1:9"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ.setdefault("ADMIN_USERNAME", "smoke")
os.environ.setdefault("ADMIN_PASSWORD", "smoke1234")
os.environ.setdefault("SECRET_KEY", "smoke")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_VERDE, _ROJO, _GRIS, _FIN = "\033[32m", "\033[31m", "\033[90m", "\033[0m"


def _color(txt: str, c: str) -> str:
    return f"{c}{txt}{_FIN}" if sys.stdout.isatty() else txt


def _psql(*sql: str, base: str = "postgres", check: bool = True) -> bool:
    cmd = [str(_PG / "psql.exe"), "-U", "postgres", "-h", "127.0.0.1", "-d", base, "-q"]
    for s in sql:
        cmd += ["-c", s]
    env = {**os.environ, "PGPASSWORD": "postgres"}
    r = subprocess.run(
        cmd, check=check, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    return r.returncode == 0


def _crear_base() -> None:
    _psql(f"DROP DATABASE IF EXISTS {_BASE};", f"CREATE DATABASE {_BASE};")
    alembic = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "alembic.exe"
    r = subprocess.run(
        [str(alembic), "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "DATABASE_URL": _URL},
        capture_output=True, text=True,
        # `encoding` explícito: sin esto Python decodifica con la cp1252 de la
        # consola y los acentos de los mensajes de migración revientan el hilo
        # lector con UnicodeDecodeError. No corta la corrida —el traceback sale
        # de un thread— pero tapa de ruido justo la pantalla que hay que leer.
        encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(r.stdout, r.stderr, file=sys.stderr)
        raise SystemExit("No se pudo migrar la base de prueba.")


async def _correr(carpeta: Path) -> int:
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from app.db.models import Cheque, ChequeTipo, MovimientoCaja
    from app.db.session import engine
    from app.services.ia import claude as ia
    from app.services.whatsapp.dispatcher import dispatch

    imagenes = sorted(
        p for p in carpeta.iterdir()
        if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    if not imagenes:
        print(f"No hay imágenes en {carpeta}", file=sys.stderr)
        return 2

    problemas = 0
    for ruta in imagenes:
        esperado: dict[str, Any] = {}
        if (js := ruta.with_suffix(".json")).exists():
            esperado = json.loads(js.read_text(encoding="utf-8"))
        mensaje = esperado.get("mensaje", "cargame este echeq al 15")

        print(f"\n▸ {ruta.name}  (\"{mensaje}\")")
        mime = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
        datos = ruta.read_bytes()

        result = await ia.extraer_intencion(
            text=mensaje, image_bytes=datos, history=[], media_mime_type=mime
        )
        if result.intent != "REGISTRAR_CHEQUE":
            print(_color(f"  ✗ intent {result.intent}: no llegó a cargar", _ROJO))
            problemas += 1
            continue

        with Session(engine) as db:
            antes = set(db.scalars(select(Cheque.id)))
            try:
                _, respuesta = dispatch(db, "smoke", result, foto=(datos, mime))
            except Exception as exc:
                print(_color(f"  ✗ el dispatcher falló: {exc}", _ROJO))
                problemas += 1
                continue

            nuevos = [c for c in db.scalars(select(Cheque)) if c.id not in antes]
            if not nuevos:
                print(_color("  ✗ no quedó ningún cheque en la base", _ROJO))
                problemas += 1
                continue

            for ch in nuevos:
                nro = ch.nro_cheque or "(sin número)"
                print(f"  guardado: Nº {nro} · {ch.banco or 'sin banco'} · "
                      f"${ch.monto:,.2f} · pago {ch.fecha_pago} · {ch.tipo.value}")

                # La plata: comprar el cheque tiene que sacar de la caja lo que
                # vale, no el nominal. Es el error que nadie ve hasta el cierre.
                egresos = list(db.scalars(
                    select(MovimientoCaja).where(MovimientoCaja.referencia_id == ch.id)
                ))
                neto = (ch.monto * (100 - ch.porcentaje_compra) / 100).quantize(ch.monto)
                if not egresos:
                    print(_color("  ✗ no asentó el egreso de compra en la caja", _ROJO))
                    problemas += 1
                elif egresos[0].monto != neto:
                    print(_color(
                        f"  ✗ la caja salió por ${egresos[0].monto:,.2f} y el neto "
                        f"es ${neto:,.2f}", _ROJO))
                    problemas += 1
                else:
                    print(f"  caja: egreso de ${egresos[0].monto:,.2f} "
                          f"({ch.porcentaje_compra}% de descuento) ✓")

                if ch.tipo != ChequeTipo.ELECTRONICO:
                    print(_color("  ✗ quedó cargado como PAPEL, no como e-cheq", _ROJO))
                    problemas += 1

                # El aviso de "sin número" no es cosmético: sin él el operador no
                # sabe que ese cheque no lo va a poder vender por chat.
                if ch.nro_cheque is None and "Sin número" not in respuesta:
                    print(_color("  ✗ no avisó que el cheque quedó sin número", _ROJO))
                    problemas += 1

        print(_color("  ── comprobante que recibe el operador ──", _GRIS))
        for linea in respuesta.splitlines():
            print(_color(f"  │ {linea}", _GRIS))

    # Postgres no borra una base con conexiones abiertas, y el pool del engine
    # deja las suyas vivas: sin esto, el DROP del final falla.
    engine.dispose()
    return problemas


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carpeta", type=Path)
    parser.add_argument("--conservar", action="store_true",
                        help="no borrar la base al terminar, para mirarla con psql")
    args = parser.parse_args()

    if not args.carpeta.is_dir():
        print(f"No existe la carpeta {args.carpeta}", file=sys.stderr)
        return 2

    print(f"Base de prueba {_BASE} (local) — llamadas reales a la API")
    _crear_base()
    try:
        problemas = asyncio.run(_correr(args.carpeta))
    finally:
        if not args.conservar:
            # Sin `check`: que no se pueda borrar la base de prueba es un detalle
            # de limpieza, no un motivo para tapar el resultado con un traceback.
            if not _psql(f"DROP DATABASE IF EXISTS {_BASE};", check=False):
                print(_color(f"\n(no se pudo borrar {_BASE}; hacelo a mano)", _GRIS))
        else:
            print(f"\nBase conservada: {_BASE}")

    print()
    if problemas:
        print(_color(f"{problemas} problema(s) en el camino foto → base.", _ROJO))
        return 1
    print(_color("Todo el camino anduvo: la foto entró, el cheque quedó y la caja cuadra.", _VERDE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
