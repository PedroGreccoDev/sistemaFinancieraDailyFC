"""Alta de deudas de cliente desde el chat (§2.b) y su distinción de los pasivos.

"Le debo a X" y "X me debe" se dicen casi igual y significan lo contrario. El
error no es simétrico ni visible: una deuda de cliente DESCUENTA la caja del día
(salió la plata) mientras que registrar un pasivo no la mueve, así que anotar uno
por el otro descuadra la caja por una operación que nunca ocurrió, y el operador
no tiene cómo notarlo salvo leyendo el reporte.

Estos tests custodian que el prompt siga marcando la diferencia y que los dos
handlers no se crucen. Unitarios puros: no llaman al modelo ni tocan la BD.
"""

from __future__ import annotations

import inspect

from app.services.ia.claude import INTENTS, _SYSTEM_PROMPT
from app.services.whatsapp import dispatcher


def _seccion_deuda_cliente() -> str:
    """La sección 10b del prompt, con su bloque de dirección."""
    return _SYSTEM_PROMPT.split("10b. REGISTRAR_DEUDA_CLIENTE")[1].split(
        "11. MOVIMIENTO_EFECTIVO"
    )[0]


def test_el_intent_esta_en_la_lista_blanca() -> None:
    """Si no está en INTENTS, el parser lo descarta a DESCONOCIDO y el bot
    responde "no entendí" en vez de registrar la deuda."""
    assert "REGISTRAR_DEUDA_CLIENTE" in INTENTS


def test_el_prompt_distingue_las_tres_direcciones() -> None:
    """Las tres formas de "deuda" que el operador puede decir tienen que estar
    contrastadas en el mismo lugar: lo que el negocio debe, lo que el cliente
    debe y el préstamo con cuotas."""
    seccion = _seccion_deuda_cliente()

    assert "REGISTRAR_DEUDA (el negocio debe)" in seccion
    assert "REGISTRAR_DEUDA_CLIENTE (el cliente debe)" in seccion
    assert "NUEVO_PRESTAMO" in seccion
    # Las frases del operador, que son lo que el modelo va a tener que reconocer.
    assert "le debo a X" in seccion
    assert "X me debe" in seccion


def test_el_prompt_avisa_que_confundirse_mueve_la_caja() -> None:
    """La regla no alcanza con enunciarla: el prompt tiene que decir por qué
    importa, que es lo que hace que el modelo no la trate como un matiz."""
    seccion = _seccion_deuda_cliente()
    assert "DESCUENTA la caja" in seccion
    assert "ACLARACION_REQUERIDA" in seccion  # dirección poco clara → preguntar


def test_sin_cuotas_no_es_un_prestamo() -> None:
    """"Le presté 100 lucas a Kiosco" cae justo entre préstamo y deuda libre.
    Sin esta regla el modelo elige por su cuenta y arma un cuadro de cuotas que
    el operador nunca pactó."""
    seccion = _seccion_deuda_cliente()
    assert "SIN CUOTAS NO ES PRÉSTAMO" in seccion


def test_fiar_plata_no_es_fiar_un_cheque() -> None:
    """En este negocio "fiar" ya significa entregar un CHEQUE a crédito. Sin la
    aclaración, "le fié 50 mil" se iría a FIAR_CHEQUE y pediría un número de
    cheque que no existe."""
    seccion = _seccion_deuda_cliente()
    assert "FIAR_CHEQUE" in seccion


def test_el_dispatcher_rutea_el_intent() -> None:
    """Un intent aceptado por el parser pero sin rama en el dispatcher se cae al
    fondo del if y el operador ve un error genérico."""
    fuente = inspect.getsource(dispatcher.dispatch)
    assert 'intent == "REGISTRAR_DEUDA_CLIENTE"' in fuente
    assert hasattr(dispatcher, "_registrar_deuda_cliente")


def test_los_dos_handlers_no_se_cruzan() -> None:
    """El de cliente crea una deuda simple; el del negocio, un pasivo. Si un
    refactor cruzara los cables, la plata quedaría anotada al revés y la caja
    del día se movería (o dejaría de moverse) sin que nadie lo pida."""
    cliente = inspect.getsource(dispatcher._registrar_deuda_cliente)
    negocio = inspect.getsource(dispatcher._registrar_deuda)

    assert "DeudaSimpleCreate" in cliente
    assert "create_deuda_simple" in cliente
    assert "PasivoCreate" not in cliente

    assert "PasivoCreate" in negocio
    assert "DeudaSimpleCreate" not in negocio


def test_ambos_handlers_exigen_el_concepto() -> None:
    """Sin la razón escrita, en un mes nadie puede reconstruir por qué se
    entregó esa plata. El prompt lo pide y el handler lo vuelve a exigir."""
    cliente = inspect.getsource(dispatcher._registrar_deuda_cliente)
    negocio = inspect.getsource(dispatcher._registrar_deuda)

    assert '_req_str(data, "concepto")' in cliente
    assert '_req_str(data, "concepto")' in negocio


def test_la_respuesta_dice_que_salio_plata_de_la_caja() -> None:
    """Es el control del operador: si quiso anotar un pasivo (que no mueve la
    caja) y el bot le contesta que salió plata, lo corrige en el momento en vez
    de descubrirlo al cerrar el día."""
    cliente = inspect.getsource(dispatcher._registrar_deuda_cliente)
    assert "Salió de caja" in cliente
