"""Leer los bugs y armar el documento.

`bugs.py` los anota; este módulo los lee. Están separados porque tienen dueños
distintos: el registro corre solo y no puede fallar nunca, mientras que esto se
consulta a mano, cuando alguien se sienta a mirar qué se rompió.

**El documento es una vista, no una fuente.** `docs/BUGS.md` se regenera entero
desde la tabla cada vez —por eso lleva el aviso de no editarlo a mano—: si
alguien anota ahí el diagnóstico de un bug, la próxima corrida se lo lleva
puesto. Lo que hay que conservar va en `notas`, que sí vive en la base y el
documento imprime.

Ver §Registro de bugs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import Bug
from app.services.exceptions import NotFoundError, ValidationError

ESTADOS = ("ABIERTO", "EN_CURSO", "CERRADO")

# Cómo se titula cada grupo en el documento. El orden es el de lectura: lo que
# está roto arriba, lo resuelto al final.
_SECCIONES = (
    ("ABIERTO", "🔴 Abiertos"),
    ("EN_CURSO", "🟡 En curso"),
    ("CERRADO", "✅ Cerrados"),
)


@dataclass
class Resumen:
    """Cuántos hay de cada cosa. Es lo que cierra una sesión de testing."""

    total:       int
    abiertos:    int
    en_curso:    int
    cerrados:    int
    ocurrencias: int
    por_origen:  dict[str, int]


# ══════════════════════════════════════════════════════════════════════
#  Consultas
# ══════════════════════════════════════════════════════════════════════

def listar(
    db: Session,
    *,
    estado: str | None = None,
    origen: str | None = None,
    sesion_test: str | None = None,
    limite: int = 200,
) -> list[Bug]:
    """Los bugs que importan primero.

    El orden es **por ocurrencias y después por fecha**: lo que más veces se
    rompe es lo que más molesta, y ordenar solo por fecha pondría arriba el
    error que pasó una vez hace un minuto por encima del que viene fallando
    trescientas veces desde ayer.
    """
    stmt = sa.select(Bug)
    if estado is not None:
        stmt = stmt.where(Bug.estado == estado)
    if origen is not None:
        stmt = stmt.where(Bug.origen == origen)
    if sesion_test is not None:
        stmt = stmt.where(Bug.sesion_test == sesion_test)

    stmt = stmt.order_by(Bug.ocurrencias.desc(), Bug.ultima_vez.desc()).limit(limite)
    return list(db.scalars(stmt))


def obtener(db: Session, bug_id: int) -> Bug:
    bug = db.get(Bug, bug_id)
    if bug is None:
        raise NotFoundError(f"No existe el bug #{bug_id}.")
    return bug


def cambiar_estado(
    db: Session, bug_id: int, *, estado: str, notas: str | None = None
) -> Bug:
    """Marca un bug como en curso o cerrado, y le deja el diagnóstico escrito.

    Cerrar no borra nada: si el bug vuelve a ocurrir, el registro lo **reabre**
    solo y lo avisa (ver `bugs._persistir`). Cerrar es decir "creemos que está
    arreglado", y que reaparezca es justamente la información que hace falta.
    """
    if estado not in ESTADOS:
        raise ValidationError(f"Estado inválido: {estado}. Debe ser uno de {ESTADOS}.")

    bug = obtener(db, bug_id)
    bug.estado = estado
    if notas is not None:
        bug.notas = notas
    db.commit()
    db.refresh(bug)
    return bug


def resumir(db: Session, *, sesion_test: str | None = None) -> Resumen:
    """Los números de conjunto, sin traerse las filas."""
    filtro = [] if sesion_test is None else [Bug.sesion_test == sesion_test]

    por_estado = dict(
        db.execute(
            sa.select(Bug.estado, sa.func.count())
            .where(*filtro)
            .group_by(Bug.estado)
        ).all()
    )
    por_origen = dict(
        db.execute(
            sa.select(Bug.origen, sa.func.count())
            .where(*filtro)
            .group_by(Bug.origen)
        ).all()
    )
    ocurrencias = (
        db.execute(sa.select(sa.func.sum(Bug.ocurrencias)).where(*filtro)).scalar() or 0
    )

    return Resumen(
        total=sum(por_estado.values()),
        abiertos=por_estado.get("ABIERTO", 0),
        en_curso=por_estado.get("EN_CURSO", 0),
        cerrados=por_estado.get("CERRADO", 0),
        ocurrencias=int(ocurrencias),
        por_origen=por_origen,
    )


# ══════════════════════════════════════════════════════════════════════
#  El documento
# ══════════════════════════════════════════════════════════════════════

def _fecha(momento: datetime | None) -> str:
    if momento is None:
        return "—"
    from app.core.fechas import datetime_local

    return datetime_local(momento).strftime("%d/%m/%Y %H:%M")


def traceback_legible(detalle: str, *, tope_lineas: int = 120) -> str:
    """Saca del traceback los frames de librerías, dejando el código propio.

    Un error de un endpoint llega con quince frames de starlette y uvicorn antes
    del primero que es nuestro. Guardados están bien —el detalle completo queda
    en la tabla y se ve por `GET /bugs/{id}`—, pero impresos en el documento
    entierran la línea que importa entre pilas de `middleware/errors.py`, y un
    documento que no se puede leer de un vistazo no se lee.

    Los frames descartados se cuentan en un marcador en vez de desaparecer: si
    el error viene de adentro de una librería, hay que poder verlo.
    """
    lineas = detalle.rstrip().splitlines()
    salida: list[str] = []
    salteados = 0
    i = 0

    while i < len(lineas):
        linea = lineas[i]
        es_frame = linea.lstrip().startswith('File "')

        # Un frame son varias líneas, no dos: desde Python 3.12 vienen el
        # `File "..."`, el renglón de código y una tercera con los `^^^^` que
        # marcan la columna. Se van todas juntas o el marcador de columna queda
        # colgado, señalando un código que ya no está.
        cuerpo = [linea]
        j = i + 1
        if es_frame:
            while (
                j < len(lineas)
                and lineas[j].startswith(" ")
                and not lineas[j].lstrip().startswith('File "')
            ):
                cuerpo.append(lineas[j])
                j += 1

        # En minúsculas: en Windows la stdlib vive en `...\Lib\asyncio\...` con
        # mayúscula, y comparar tal cual dejaría pasar todos esos frames.
        ruta = linea.replace("\\", "/").lower()
        if es_frame and ("site-packages" in ruta or "/lib/" in ruta):
            salteados += 1
        else:
            if salteados:
                salida.append(f"  … {salteados} frame(s) de librerías …")
                salteados = 0
            salida += cuerpo

        i = j if es_frame else i + 1

    if salteados:
        salida.append(f"  … {salteados} frame(s) de librerías …")

    if len(salida) > tope_lineas:
        # Las últimas líneas son el tipo de excepción y su mensaje: eso no se
        # corta nunca, es lo primero que se lee.
        recorte = len(salida) - tope_lineas
        salida = salida[: tope_lineas - 10] + [f"  … {recorte} líneas recortadas …"] + salida[-9:]

    return "\n".join(salida)


def _bloque_abierto(bug: Bug) -> list[str]:
    """Un bug que sigue vivo: con todo lo que hace falta para atacarlo."""
    lineas = [
        f"### #{bug.id} — {bug.titulo}",
        "",
        f"- **Dónde:** `{bug.ubicacion}`" + (f" · `{bug.ambito}`" if bug.ambito else ""),
        f"- **Origen:** {bug.origen}",
        f"- **Ocurrencias:** {bug.ocurrencias} "
        f"(primera {_fecha(bug.primera_vez)}, última {_fecha(bug.ultima_vez)})",
    ]
    if bug.sesion_test:
        lineas.append(f"- **Encontrado en la corrida:** `{bug.sesion_test}`")
    if bug.notas:
        lineas.append(f"- **Notas:** {bug.notas}")

    if bug.detalle:
        # Plegado: el traceback es lo que se necesita para arreglarlo y lo que
        # haría ilegible la lista si estuviera siempre abierto.
        lineas += [
            "",
            "<details><summary>Detalle</summary>",
            "",
            "```",
            traceback_legible(bug.detalle),
            "```",
            "",
            "</details>",
        ]
    lineas.append("")
    return lineas


def _linea_cerrado(bug: Bug) -> str:
    """Un bug cerrado ocupa un renglón: está para consultarlo, no para leerlo."""
    notas = f" — {bug.notas}" if bug.notas else ""
    return (
        f"- **#{bug.id}** {bug.titulo} · `{bug.ubicacion}` · "
        f"{bug.ocurrencias} ocurrencia{'s' if bug.ocurrencias != 1 else ''}{notas}"
    )


def render_markdown(bugs: list[Bug], *, generado_en: datetime) -> str:
    """Arma `docs/BUGS.md` entero. Función pura: no toca la base ni el reloj.

    `generado_en` entra por parámetro y no se lee de `datetime.now()` para poder
    testear la salida completa contra un texto fijo — la misma convención que el
    resto del proyecto.
    """
    por_estado: dict[str, list[Bug]] = {estado: [] for estado in ESTADOS}
    for bug in bugs:
        por_estado.setdefault(bug.estado, []).append(bug)

    # Lo que no cae en ninguna de las tres secciones se imprime igual, al final.
    # Sin esto, un estado nuevo hace que el bug **desaparezca del documento sin
    # fallar** — la peor forma de perder un bug: el aviso llegó con su número y
    # el documento no lo tiene.
    sueltos = [b for estado, lista in por_estado.items() if estado not in ESTADOS for b in lista]

    total = len(bugs)
    partes = [
        f"{len(por_estado.get(estado, []))} {etiqueta.split(' ', 1)[1].lower()}"
        for estado, etiqueta in _SECCIONES
    ]
    if sueltos:
        partes.append(f"{len(sueltos)} sin clasificar")
    conteo = " · ".join(partes)

    salida = [
        "# Bugs — Sistema Financiera DailyFC",
        "",
        "> Generado por `scripts/exportar_bugs.py` desde la tabla `bugs`.",
        "> **No editar a mano:** se regenera entero y cualquier cambio se pierde.",
        "> Lo que haya que conservar va en las notas del bug, que viven en la base.",
        "",
        f"**{total} bug{'s' if total != 1 else ''}** · {conteo}",
        "",
        f"Generado el {_fecha(generado_en)} ART.",
        "",
    ]

    if total == 0:
        salida += ["---", "", "Todavía no se registró ningún bug.", ""]
        return "\n".join(salida)

    for estado, titulo in _SECCIONES:
        del_grupo = por_estado.get(estado, [])
        if not del_grupo:
            continue

        salida += ["---", "", f"## {titulo}", ""]
        if estado == "CERRADO":
            salida += [_linea_cerrado(bug) for bug in del_grupo]
            salida.append("")
        else:
            for bug in del_grupo:
                salida += _bloque_abierto(bug)

    if sueltos:
        salida += ["---", "", "## ❓ Sin clasificar", ""]
        salida += [
            f"Estos bugs tienen un estado que el documento no conoce "
            f"({', '.join(sorted({b.estado for b in sueltos}))}).",
            "",
        ]
        for bug in sueltos:
            salida += _bloque_abierto(bug)

    return "\n".join(salida)
