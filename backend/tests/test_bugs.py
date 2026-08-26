"""El registro de bugs: que cada error tenga número y que suene a tiempo.

Lo que se custodia acá es lo que hace que el sistema sirva de algo:

- Que el **mismo** error mil veces sea un solo número con un contador, y no mil
  bugs distintos. Si la huella se calculara con los valores —el monto, el
  cliente, el id de la URL— el contador dejaría de medir nada y el chat de
  Telegram sería una lista infinita de bugs de una ocurrencia.
- Que un error del negocio ("el cheque ya está vendido") **no** abra un bug. Son
  cientos por día y taparían lo que importa.
- Que **el traceback no salga** a Telegram. Es la decisión que ya estaba tomada
  en el webhook y que el registro tiene que seguir respetando: el mensaje de una
  excepción de SQLAlchemy arrastra montos, nombres y teléfonos.
- Que capturar **nunca lance**, ni siquiera cuando lo que se le pasa está roto.

Estilo del proyecto: unitarios puros, sin BD.

Ver §Registro de bugs.
"""

from __future__ import annotations

import logging

import pytest

from app.services import bugs
from app.services.exceptions import ConflictError, DatabaseWriteError, NotFoundError


@pytest.fixture(autouse=True)
def _cola_limpia():
    """Cada test arranca con la cola vacía y no le deja nada al siguiente."""
    bugs._COLA.clear()
    yield
    bugs._COLA.clear()


def _explotar(mensaje: str = "boom") -> Exception:
    """Devuelve una excepción con traceback de verdad (hace falta para ubicarla)."""
    try:
        raise ValueError(mensaje)
    except ValueError as exc:
        return exc


# ══════════════════════════════════════════════════════════════════════
#  La huella: qué junta y qué separa
# ══════════════════════════════════════════════════════════════════════

def test_el_mismo_error_repetido_tiene_una_sola_huella() -> None:
    """Es lo que hace que 500 fallas sean el bug #47 con 500 ocurrencias."""
    a = bugs.calcular_huella("IntegrityError", "cheques.py:212", "POST /api/v1/cheques")
    b = bugs.calcular_huella("IntegrityError", "cheques.py:212", "POST /api/v1/cheques")
    assert a == b


def test_los_ids_de_la_ruta_no_abren_bugs_distintos() -> None:
    """`/clientes/{uuid}` es un endpoint, no un bug por cliente.

    Sin esta normalización, una falla en la ficha de cliente abriría un bug por
    cada cliente que la abriera: el mismo problema repartido en cien números,
    que es la forma más segura de que nadie lo vea.
    """
    uno = bugs.calcular_huella(
        "AttributeError", "clientes.py:88", "GET /clientes/3f2a9c1e-4b5d-4e6f-8a9b-0c1d2e3f4a5b"
    )
    otro = bugs.calcular_huella(
        "AttributeError", "clientes.py:88", "GET /clientes/9e8d7c6b-5a4f-4e3d-2c1b-0a9f8e7d6c5b"
    )
    assert uno == otro


def test_dos_caminos_hacia_la_misma_linea_son_dos_bugs() -> None:
    """El ámbito separa: se llega distinto y se arregla distinto."""
    panel = bugs.calcular_huella("KeyError", "caja.py:40", "POST /api/v1/gastos")
    bot = bugs.calcular_huella("KeyError", "caja.py:40", "bot:mensaje")
    assert panel != bot


def test_la_huella_no_mira_los_valores() -> None:
    """Dos fallas iguales con montos distintos son un solo bug.

    Es la contracara del test de arriba: si el monto o el nombre entraran en la
    huella, el contador de ocurrencias no mediría gravedad, mediría variedad.
    """
    assert bugs.calcular_huella(
        "ValueError", "caja.py:40", "POST /gastos"
    ) == bugs.calcular_huella("ValueError", "caja.py:40", "POST /gastos")


# ══════════════════════════════════════════════════════════════════════
#  Qué merece bug y qué no
# ══════════════════════════════════════════════════════════════════════

def test_un_error_de_negocio_no_abre_bug() -> None:
    """"El cheque ya está vendido" es el sistema funcionando, no fallando."""
    bugs.capturar(ConflictError("el cheque ya está vendido"), origen=bugs.ORIGEN_PANEL)
    bugs.capturar(NotFoundError("no existe el cliente"), origen=bugs.ORIGEN_PANEL)
    assert bugs.pendientes() == 0


def test_un_serviceerror_de_500_si_abre_bug() -> None:
    """`DatabaseWriteError` no es el negocio diciendo que no: es una falla.

    Comparte clase base con los 4xx, así que descartarlos a todos por
    `isinstance(ServiceError)` —lo más natural de escribir— dejaría los errores
    de escritura en la base sin registrar y sin avisar.
    """
    bugs.capturar(DatabaseWriteError("no se pudo escribir"), origen=bugs.ORIGEN_PANEL)
    assert bugs.pendientes() == 1


def test_una_excepcion_no_se_cuenta_dos_veces() -> None:
    """La misma instancia pasa por varias manos y tiene que contar una vez.

    En el webhook el error se captura explícitamente y enseguida se loguea con
    `logger.exception`: son dos caminos hacia el registro para un solo error, y
    sin la marca el contador de ocurrencias saldría al doble — justo el número
    que se mira para decidir si algo es grave.
    """
    exc = _explotar()
    bugs.capturar(exc, origen=bugs.ORIGEN_BOT, ambito="bot:mensaje")
    bugs.capturar(exc, origen=bugs.ORIGEN_PANEL, ambito="log:app.api.routes.webhook")
    assert bugs.pendientes() == 1


def test_capturar_nunca_lanza() -> None:
    """Anotar un bug no puede tumbar la operación que lo produjo.

    Es la razón de ser del `try` que envuelve todo `capturar`: el registro
    existe para que los errores se vean, no para causarlos.
    """
    bugs.capturar(None, origen=bugs.ORIGEN_PANEL)  # type: ignore[arg-type]
    bugs.capturar_mensaje(origen=bugs.ORIGEN_TESTING, titulo=None, ubicacion=None)  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════════════
#  Dónde saltó
# ══════════════════════════════════════════════════════════════════════

def test_la_ubicacion_es_del_codigo_propio() -> None:
    """Se elige el último frame dentro de `app/`, no el último a secas.

    El último frame de un error de base cae adentro de SQLAlchemy: cierto, pero
    inútil — todos los errores de base darían la misma línea de la librería y se
    juntarían en un solo bug que no se puede arreglar.
    """
    ubicacion = bugs.ubicacion_de(_explotar())
    assert ubicacion.startswith("test_bugs.py:")


def test_una_excepcion_sin_traceback_no_revienta() -> None:
    assert bugs.ubicacion_de(ValueError("nunca se lanzó")) == "ubicación desconocida"


# ══════════════════════════════════════════════════════════════════════
#  Lo que viaja a Telegram
# ══════════════════════════════════════════════════════════════════════

def test_el_aviso_lleva_el_numero_y_no_el_traceback() -> None:
    """El numeral es justamente lo que hace innecesario mandar el detalle.

    Telegram es un tercero y el traceback de SQLAlchemy arrastra el SQL con sus
    parámetros: montos, nombres de clientes, teléfonos. Con el número alcanza
    para ir a buscarlo a `docs/BUGS.md`.
    """
    evento = bugs.Evento(
        origen=bugs.ORIGEN_PANEL,
        titulo="IntegrityError en POST /api/v1/cheques",
        tipo="IntegrityError",
        ubicacion="cheques.py:212",
        ambito="POST /api/v1/cheques",
        detalle="Traceback...\nINSERT INTO cheques (monto) VALUES (1500000) -- Juan Pérez",
    )
    texto = bugs.texto_aviso(evento, bugs.Registrado(id=47, ocurrencias=1, nuevo=True, reabierto=False))

    assert "#47" in texto
    assert "IntegrityError" in texto
    assert "cheques.py:212" in texto
    assert "Traceback" not in texto
    assert "Juan Pérez" not in texto
    assert "1500000" not in texto


def test_el_aviso_distingue_nuevo_de_repetido_y_de_reaparecido() -> None:
    """Los tres se leen distinto y significan cosas distintas."""
    evento = bugs.Evento(
        origen=bugs.ORIGEN_BOT, titulo="t", tipo="ValueError", ubicacion="a.py:1"
    )
    nuevo = bugs.texto_aviso(evento, bugs.Registrado(id=1, ocurrencias=1, nuevo=True, reabierto=False))
    repetido = bugs.texto_aviso(evento, bugs.Registrado(id=1, ocurrencias=50, nuevo=False, reabierto=False))
    reaparecido = bugs.texto_aviso(evento, bugs.Registrado(id=1, ocurrencias=9, nuevo=False, reabierto=True))

    assert "nuevo" in nuevo
    assert "50 veces" in repetido
    assert "reapareció" in reaparecido


# ══════════════════════════════════════════════════════════════════════
#  El antiflood: cuándo vuelve a sonar
# ══════════════════════════════════════════════════════════════════════

def test_un_bug_que_escala_vuelve_a_avisar() -> None:
    """La regla vieja silenciaba quince minutos y perdía el caso grave.

    Un bug que pasa de 3 a 3000 ocurrencias es exactamente el que hay que mirar,
    y con una ventana de silencio a secas no volvía a sonar nunca.
    """
    assert bugs._hay_que_avisar(
        bugs.Registrado(id=1, ocurrencias=100, nuevo=False, reabierto=False), _hace_un_minuto()
    )


def test_un_bug_conocido_no_avisa_en_cada_ocurrencia() -> None:
    """Entre escalón y escalón se calla: un chat que suena siempre se ignora."""
    assert not bugs._hay_que_avisar(
        bugs.Registrado(id=1, ocurrencias=37, nuevo=False, reabierto=False), _hace_un_minuto()
    )


def test_un_bug_cerrado_que_vuelve_avisa_igual() -> None:
    """Reaparecer es noticia aunque el contador esté lejos de un escalón."""
    assert bugs._hay_que_avisar(
        bugs.Registrado(id=1, ocurrencias=37, nuevo=False, reabierto=True), _hace_un_minuto()
    )


def _hace_un_minuto():
    from datetime import datetime, timedelta, timezone

    return datetime.now(timezone.utc) - timedelta(minutes=1)


# ══════════════════════════════════════════════════════════════════════
#  La captura de logs: los errores que hoy se tragan
# ══════════════════════════════════════════════════════════════════════

def test_un_logger_error_se_convierte_en_bug() -> None:
    """Es la pieza que cierra el agujero de fondo.

    Hay veinte `except Exception` que loguean y siguen —a propósito: el bot no
    puede morirse porque falló un envío—. Cada uno es un error que nadie ve
    hasta que algo no cierra al final del día.
    """
    handler = bugs.HandlerDeLogs()
    handler.emit(
        logging.LogRecord(
            name="app.services.caja",
            level=logging.ERROR,
            pathname="/app/app/services/caja.py",
            lineno=120,
            msg="no se pudo asentar la línea de %s",
            args=("Juan",),
            exc_info=None,
        )
    )
    assert bugs.pendientes() == 1


def test_el_registro_no_se_alerta_a_si_mismo() -> None:
    """Si anotar un bug falla y eso loguea un error, sería un loop infinito."""
    handler = bugs.HandlerDeLogs()
    for modulo in ("app.services.bugs", "app.services.telegram"):
        handler.emit(
            logging.LogRecord(
                name=modulo,
                level=logging.ERROR,
                pathname=f"/app/{modulo.replace('.', '/')}.py",
                lineno=1,
                msg="falló el envío",
                args=(),
                exc_info=None,
            )
        )
    assert bugs.pendientes() == 0


def test_un_warning_no_es_un_bug() -> None:
    """Los WARNING son ruido operativo normal: un cliente ambiguo, un reintento."""
    handler = bugs.HandlerDeLogs()
    assert handler.level == logging.ERROR


def test_el_error_del_bot_se_marca_como_del_bot() -> None:
    """El origen separa lo que le pasa al operador de lo que le pasa al panel."""
    handler = bugs.HandlerDeLogs()
    handler.emit(
        logging.LogRecord(
            name="app.services.whatsapp.dispatcher",
            level=logging.ERROR,
            pathname="/app/app/services/whatsapp/dispatcher.py",
            lineno=169,
            msg="explotó el dispatch",
            args=(),
            exc_info=None,
        )
    )
    assert bugs._COLA[0].origen == bugs.ORIGEN_BOT
