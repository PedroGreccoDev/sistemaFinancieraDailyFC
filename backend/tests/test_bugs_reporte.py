"""El documento de bugs: que se pueda leer y que no mienta.

`docs/BUGS.md` es lo que se abre cuando llega un aviso con un número. Lo que se
custodia acá:

- Que **el número esté**, que es todo el punto: el aviso dice "#47" y el
  documento tiene que ser donde se encuentra el 47.
- Que un bug cerrado ocupe **un renglón** y uno abierto traiga el traceback. Si
  los cerrados se imprimieran enteros, un archivo con cien bugs viejos taparía
  los cuatro que están rotos hoy.
- Que **avise que se regenera**: alguien que anote ahí el diagnóstico lo pierde
  en la próxima corrida, y el lugar para eso son las notas del bug.

Estilo del proyecto: unitarios puros, sin BD — `render_markdown` recibe los
objetos y la fecha por parámetro, así que la salida se compara contra un texto
fijo sin depender del reloj.

Ver §Registro de bugs.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.models import Bug
from app.services import bugs_reporte


def _bug(
    id_: int,
    *,
    estado: str = "ABIERTO",
    ocurrencias: int = 1,
    titulo: str = "ValueError en POST /api/v1/cheques",
    detalle: str = "Traceback (most recent call last):\n  ...\nValueError: boom",
    notas: str | None = None,
    sesion_test: str | None = None,
) -> Bug:
    """Un Bug en memoria, sin pasar por la base."""
    bug = Bug()
    bug.id = id_
    bug.huella = f"huella-{id_}"
    bug.origen = "panel"
    bug.titulo = titulo
    bug.tipo = "ValueError"
    bug.ubicacion = "cheques.py:212"
    bug.ambito = "POST /api/v1/cheques"
    bug.detalle = detalle
    bug.contexto = None
    bug.ocurrencias = ocurrencias
    bug.primera_vez = datetime(2026, 8, 20, 13, 12, tzinfo=timezone.utc)
    bug.ultima_vez = datetime(2026, 8, 25, 21, 4, tzinfo=timezone.utc)
    bug.estado = estado
    bug.notas = notas
    bug.sesion_test = sesion_test
    bug.avisos_enviados = 0
    bug.ultimo_aviso_at = None
    return bug


_GENERADO = datetime(2026, 8, 25, 23, 30, tzinfo=timezone.utc)


# ══════════════════════════════════════════════════════════════════════
#  Que el número sea encontrable
# ══════════════════════════════════════════════════════════════════════

def test_el_numeral_encabeza_cada_bug() -> None:
    """El aviso de Telegram dice "#47" y no manda nada más: acá se encuentra."""
    salida = bugs_reporte.render_markdown([_bug(47)], generado_en=_GENERADO)
    assert "### #47 — ValueError en POST /api/v1/cheques" in salida


def test_el_bug_abierto_trae_donde_y_cuantas_veces() -> None:
    """Es lo que hace falta para decidir si se ataca ahora o después."""
    salida = bugs_reporte.render_markdown([_bug(1, ocurrencias=312)], generado_en=_GENERADO)
    assert "`cheques.py:212`" in salida
    assert "`POST /api/v1/cheques`" in salida
    assert "**Ocurrencias:** 312" in salida


def test_el_traceback_va_plegado_y_completo() -> None:
    """En el documento sí va entero: esta es la casa, Telegram es el tercero."""
    salida = bugs_reporte.render_markdown([_bug(1)], generado_en=_GENERADO)
    assert "<details><summary>Detalle</summary>" in salida
    assert "ValueError: boom" in salida


# ══════════════════════════════════════════════════════════════════════
#  Que lo roto no quede tapado por lo resuelto
# ══════════════════════════════════════════════════════════════════════

def test_los_cerrados_ocupan_un_renglon() -> None:
    """Cien bugs viejos impresos enteros taparían los cuatro de hoy."""
    salida = bugs_reporte.render_markdown(
        [_bug(9, estado="CERRADO", notas="era el medio de pago")], generado_en=_GENERADO
    )
    assert "**#9**" in salida
    assert "era el medio de pago" in salida
    assert "<details>" not in salida


def test_los_abiertos_van_antes_que_los_cerrados() -> None:
    salida = bugs_reporte.render_markdown(
        [_bug(1), _bug(2, estado="CERRADO")], generado_en=_GENERADO
    )
    assert salida.index("🔴 Abiertos") < salida.index("✅ Cerrados")


def test_una_seccion_vacia_no_se_imprime() -> None:
    """Un "En curso" vacío es un título hueco que hay que saltear al leer."""
    salida = bugs_reporte.render_markdown([_bug(1)], generado_en=_GENERADO)
    assert "En curso" not in salida


# ══════════════════════════════════════════════════════════════════════
#  Que el documento diga lo que es
# ══════════════════════════════════════════════════════════════════════

def test_avisa_que_se_regenera_entero() -> None:
    """Sin este aviso, alguien anota el diagnóstico ahí y lo pierde."""
    salida = bugs_reporte.render_markdown([_bug(1)], generado_en=_GENERADO)
    assert "No editar a mano" in salida


def test_las_notas_del_bug_se_imprimen() -> None:
    """Es el lugar que sí sobrevive a la regeneración, y por eso tiene que verse."""
    salida = bugs_reporte.render_markdown(
        [_bug(1, notas="pasa cuando el cheque no trae banco")], generado_en=_GENERADO
    )
    assert "pasa cuando el cheque no trae banco" in salida


def test_el_conteo_del_encabezado_coincide() -> None:
    salida = bugs_reporte.render_markdown(
        [_bug(1), _bug(2), _bug(3, estado="CERRADO")], generado_en=_GENERADO
    )
    assert "**3 bugs**" in salida
    assert "2 abiertos" in salida
    assert "1 cerrados" in salida


def test_sin_bugs_lo_dice_en_vez_de_quedar_en_blanco() -> None:
    """Un archivo vacío se lee como "se rompió el export", no como "no hay bugs"."""
    salida = bugs_reporte.render_markdown([], generado_en=_GENERADO)
    assert "Todavía no se registró ningún bug" in salida
    assert "**0 bugs**" in salida


def test_la_corrida_que_lo_encontro_queda_anotada() -> None:
    """Sirve para separar lo que rompió la sesión de testing de lo de producción."""
    salida = bugs_reporte.render_markdown(
        [_bug(1, sesion_test="sesion-2026-08-25-01")], generado_en=_GENERADO
    )
    assert "`sesion-2026-08-25-01`" in salida


def test_un_estado_desconocido_no_desaparece_del_documento() -> None:
    """Si alguien mete un estado nuevo, el bug tiene que verse igual.

    El agrupador arma los grupos por estado y el bug caería en uno que las
    secciones no recorren: se perdería del documento **sin fallar**, que es la
    peor forma de perder un bug.
    """
    raro = _bug(5)
    raro.estado = "PENDIENTE_DE_REVISION"
    salida = bugs_reporte.render_markdown([raro], generado_en=_GENERADO)
    assert "#5" in salida


# ══════════════════════════════════════════════════════════════════════
#  Que el traceback se pueda leer
# ══════════════════════════════════════════════════════════════════════

_TRACEBACK_REAL = '''Traceback (most recent call last):
  File "/proy/backend/.venv/lib/site-packages/starlette/middleware/errors.py", line 165, in __call__
    await self.app(scope, receive, _send)
  File "/proy/backend/.venv/lib/site-packages/starlette/routing.py", line 715, in __call__
    await self.middleware_stack(scope, receive, send)
  File "/proy/backend/app/api/routes/cheques.py", line 212, in crear_cheque
    return service.create_cheque(db, payload)
  File "/proy/backend/app/services/cheques.py", line 88, in create_cheque
    raise ValueError("boom")
ValueError: boom'''


def test_los_frames_de_librerias_no_entierran_el_codigo_propio() -> None:
    """Quince frames de starlette antes del nuestro hacen ilegible el documento."""
    salida = bugs_reporte.traceback_legible(_TRACEBACK_REAL)

    assert "starlette" not in salida
    assert "cheques.py" in salida
    assert "create_cheque" in salida


def test_los_frames_salteados_se_cuentan_en_vez_de_desaparecer() -> None:
    """Si el error viene de adentro de una librería, hay que poder verlo."""
    assert "2 frame(s) de librerías" in bugs_reporte.traceback_legible(_TRACEBACK_REAL)


def test_el_tipo_de_excepcion_nunca_se_corta() -> None:
    """Es lo primero que se lee: sobrevive al recorte por largo."""
    largo = "Traceback (most recent call last):\n" + "\n".join(
        f'  File "/proy/backend/app/x.py", line {n}, in f\n    hacer_algo()'
        for n in range(300)
    ) + "\nValueError: el ultimo renglon"

    salida = bugs_reporte.traceback_legible(largo, tope_lineas=40)
    assert salida.splitlines()[-1] == "ValueError: el ultimo renglon"
    assert "líneas recortadas" in salida


def test_un_detalle_que_no_es_traceback_pasa_igual() -> None:
    """`capturar_mensaje` guarda texto suelto: un invariante roto, por ejemplo."""
    texto = "la caja ARS efectivo no cuadra: libro 120000, contado 118500"
    assert bugs_reporte.traceback_legible(texto) == texto


def test_el_marcador_de_columna_se_va_con_su_frame() -> None:
    """Desde Python 3.12 cada frame trae una línea de `^^^^` señalando la columna.

    Si se salteara el `File` y el código pero no el `^^^^`, quedarían marcadores
    huérfanos apuntando a un código que ya no está — y el conteo de frames se
    fragmenta en "12 frames … 1 frame … 1 frame".
    """
    con_marcadores = "\n".join([
        "Traceback (most recent call last):",
        '  File "/proy/.venv/lib/site-packages/starlette/routing.py", line 715, in __call__',
        "    await self.middleware_stack(scope, receive, send)",
        "          ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^",
        '  File "/proy/backend/app/services/caja.py", line 40, in registrar',
        "    raise ValueError('boom')",
        "ValueError: boom",
    ])

    salida = bugs_reporte.traceback_legible(con_marcadores)

    assert "^^^" not in salida
    assert salida.count("frame(s) de librerías") == 1
    assert "caja.py" in salida
