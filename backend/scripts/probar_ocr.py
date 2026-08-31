"""Banco de pruebas del OCR: pasa imágenes reales por el modelo y compara lo que leyó.

Los tests unitarios verifican el prompt como texto —que diga lo que tiene que
decir— pero no que el modelo lo obedezca mirando una foto. Eso solo se sabe
llamándolo. Este script cierra ese hueco: toma capturas reales, las pasa por el
MISMO camino que usa el bot (`ia.extraer_intencion`, mismo modelo y mismo prompt)
y muestra campo por campo qué extrajo, marcando lo que no coincide con lo
esperado.

**Cuesta plata:** cada corrida son llamadas reales a la API de Anthropic. Son
centavos, pero no es gratis. Por eso es un script y no un test de la suite.

Uso:
    # Ver qué lee de cada imagen de una carpeta
    backend\\.venv\\Scripts\\python.exe scripts/probar_ocr.py <carpeta>

    # Comparar contra lo esperado (un .json al lado de cada imagen, mismo nombre)
    backend\\.venv\\Scripts\\python.exe scripts/probar_ocr.py <carpeta> --verificar

    # Repetir cada imagen N veces: el modelo no es determinista y un acierto
    # suelto no prueba nada. 3 corridas muestran si el resultado es estable.
    backend\\.venv\\Scripts\\python.exe scripts/probar_ocr.py <carpeta> -n 3

El archivo de expectativas es un JSON con los campos que importan; los que no
figuran no se miran. `"mensaje"` (opcional) es el texto que acompaña a la foto,
para simular lo que el operador escribe junto a la captura:

    {
      "mensaje": "compré este echeq al 12",
      "intent": "REGISTRAR_CHEQUE",
      "cheques": [
        {"nro_cheque": "00001020", "monto": 1900000, "fecha_pago": "2026-09-10",
         "banco": "Galicia", "tipo": "ELECTRONICO"}
      ]
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import mimetypes
import os
import sys
from pathlib import Path
from typing import Any

# ── Guardas de entorno, ANTES de importar `app` ──────────────────────────────
# El .env del repo apunta a la base de producción y a la WAHA real. Este script
# no escribe nada, pero importar `app` levanta configuración: si algo del camino
# intentara mandar un WhatsApp o tocar la base, tiene que fallar y no acertar.
# Se fuerza con asignación directa, no setdefault: bajo `railway run` el entorno
# ya trae los valores de producción y un default no los pisaría.
os.environ["WAHA_API_URL"] = "http://127.0.0.1:9"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ["DATABASE_URL"] = "postgresql+psycopg://nadie@127.0.0.1:1/no-usar"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# La consola de Windows sale en cp1252 y revienta con acentos y símbolos. Se
# arregla acá y no con PYTHONIOENCODING para que el script funcione tal cual se
# invoca, sin una variable de entorno que hay que acordarse de poner.
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

from app.services.ia import claude as ia  # noqa: E402

_IMAGENES = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# Campos de un cheque que se comparan cuando hay expectativas. El resto de lo que
# devuelva el modelo se muestra pero no se juzga.
_CAMPOS = ("nro_cheque", "banco", "monto", "fecha_emision", "fecha_pago", "tipo")

_VERDE, _ROJO, _AMARILLO, _GRIS, _FIN = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"


def _color(txt: str, c: str) -> str:
    return f"{c}{txt}{_FIN}" if sys.stdout.isatty() else txt


def _norm(valor: Any) -> Any:
    """Compara 1900000 con "1900000.00" sin marcarlos distintos."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    txt = str(valor).strip()
    try:
        return float(txt)
    except ValueError:
        return txt.upper()


def _fmt(valor: Any) -> str:
    return "—" if valor in (None, "") else str(valor)


async def _leer(ruta: Path, mensaje: str) -> dict[str, Any]:
    mime = mimetypes.guess_type(ruta.name)[0] or "image/jpeg"
    resultado = await ia.extraer_intencion(
        text=mensaje, image_bytes=ruta.read_bytes(), history=[], media_mime_type=mime
    )
    return {
        "intent": resultado.intent,
        "data": getattr(resultado, "data", {}) or {},
        "respuesta": getattr(resultado, "respuesta_usuario", "") or "",
    }


def _cheques_de(data: dict[str, Any]) -> list[dict[str, Any]]:
    """El modelo puede mandar `cheques: [...]` o los campos sueltos (formato viejo)."""
    items = data.get("cheques")
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    return [data] if data.get("nro_cheque") or data.get("monto") else []


def _comparar(leido: dict[str, Any], esperado: dict[str, Any]) -> list[str]:
    """Devuelve la lista de diferencias. Vacía = el modelo leyó lo que debía."""
    fallas: list[str] = []

    if "intent" in esperado and leido["intent"] != esperado["intent"]:
        fallas.append(f"intent: esperaba {esperado['intent']}, leyó {leido['intent']}")

    esperados = esperado.get("cheques") or []
    leidos = _cheques_de(leido["data"])
    if len(leidos) != len(esperados):
        fallas.append(f"cantidad de cheques: esperaba {len(esperados)}, leyó {len(leidos)}")

    for i, (esp, obt) in enumerate(zip(esperados, leidos), start=1):
        for campo in _CAMPOS:
            if campo not in esp:
                continue
            if _norm(obt.get(campo)) != _norm(esp[campo]):
                fallas.append(
                    f"cheque {i} · {campo}: esperaba {_fmt(esp[campo])}, "
                    f"leyó {_fmt(obt.get(campo))}"
                )
    return fallas


def _mostrar(ruta: Path, leido: dict[str, Any]) -> None:
    print(f"  intent: {leido['intent']}")
    cheques = _cheques_de(leido["data"])
    if not cheques:
        print(_color("  (no extrajo ningún cheque)", _AMARILLO))
    for i, ch in enumerate(cheques, start=1):
        campos = "  ".join(f"{c}={_fmt(ch.get(c))}" for c in _CAMPOS)
        print(f"  cheque {i}: {campos}")
    otros = {k: v for k, v in leido["data"].items() if k not in ("cheques",) + _CAMPOS}
    if otros:
        print(_color(f"  otros campos: {json.dumps(otros, ensure_ascii=False)}", _GRIS))


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("carpeta", type=Path, help="carpeta con las imágenes a probar")
    parser.add_argument("--verificar", action="store_true",
                        help="comparar contra el .json de al lado de cada imagen")
    parser.add_argument("-n", "--corridas", type=int, default=1,
                        help="veces que se lee cada imagen (el modelo no es determinista)")
    args = parser.parse_args()

    if not args.carpeta.is_dir():
        print(f"No existe la carpeta {args.carpeta}", file=sys.stderr)
        return 2

    imagenes = sorted(p for p in args.carpeta.iterdir() if p.suffix.lower() in _IMAGENES)
    if not imagenes:
        print(f"No hay imágenes en {args.carpeta}", file=sys.stderr)
        return 2

    print(f"{len(imagenes)} imagen(es) × {args.corridas} corrida(s) — llamadas reales a la API\n")

    total = fallidas = 0
    for ruta in imagenes:
        esperado: dict[str, Any] = {}
        json_path = ruta.with_suffix(".json")
        if json_path.exists():
            esperado = json.loads(json_path.read_text(encoding="utf-8"))
        elif args.verificar:
            print(_color(f"▸ {ruta.name}: sin {json_path.name}, no se verifica", _AMARILLO))
            continue

        mensaje = esperado.get("mensaje", "")
        print(f"▸ {ruta.name}" + (f'  ("{mensaje}")' if mensaje else ""))

        for corrida in range(1, args.corridas + 1):
            if args.corridas > 1:
                print(_color(f"  — corrida {corrida}/{args.corridas}", _GRIS))
            try:
                leido = await _leer(ruta, mensaje)
            except Exception as exc:  # el detalle importa: puede ser la API caída
                print(_color(f"  ERROR llamando al modelo: {exc}", _ROJO))
                total += 1
                fallidas += 1
                continue

            _mostrar(ruta, leido)
            total += 1

            if not args.verificar or not esperado:
                continue
            fallas = _comparar(leido, esperado)
            if fallas:
                fallidas += 1
                for f in fallas:
                    print(_color(f"  ✗ {f}", _ROJO))
            else:
                print(_color("  ✓ leyó todo lo esperado", _VERDE))
        print()

    if args.verificar:
        ok = total - fallidas
        estado = _color(f"{ok}/{total} correctas", _VERDE if not fallidas else _ROJO)
        print(f"Resultado: {estado}")
        return 1 if fallidas else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
