"""Escribe `docs/BUGS.md` desde la tabla `bugs`.

    cd backend
    .\\.venv\\Scripts\\python.exe scripts\\exportar_bugs.py

El archivo se **regenera entero**: es una vista de la base, no una fuente. Lo
que haya que conservar de un bug va en sus notas (`PATCH /bugs/{id}`), que sí
viven en Postgres y el documento imprime.

Va contra la base que diga `DATABASE_URL`, así que **con el `.env` del repo lee
producción** — que para exportar está bien, es solo lectura, pero conviene
saberlo: el documento que sale es el de los bugs reales.

Ver §Registro de bugs.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

# Permite correrlo como `python scripts/exportar_bugs.py` desde `backend/`.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.services import bugs_reporte  # noqa: E402

DESTINO = Path(__file__).resolve().parent.parent.parent / "docs" / "BUGS.md"


def main() -> int:
    db = SessionLocal()
    try:
        todos = bugs_reporte.listar(db, limite=2000)
        resumen = bugs_reporte.resumir(db)
        texto = bugs_reporte.render_markdown(
            todos, generado_en=datetime.now(timezone.utc)
        )
    finally:
        db.close()

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    # UTF-8 explícito y saltos Unix: en Windows el default de `write_text` es la
    # codificación de la consola (cp1252) y los acentos del documento explotan.
    DESTINO.write_text(texto, encoding="utf-8", newline="\n")

    print(f"Escrito: {DESTINO}")
    print(
        f"  {resumen.total} bugs · {resumen.abiertos} abiertos · "
        f"{resumen.en_curso} en curso · {resumen.cerrados} cerrados"
    )
    print(f"  {resumen.ocurrencias} ocurrencias en total · por origen: {resumen.por_origen}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
