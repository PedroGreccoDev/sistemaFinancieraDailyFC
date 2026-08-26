"""Red bajo los intents que todavía cargan de a una operación.

Los cinco intents de cheques y los gastos aceptan un array; el resto no. Cuando el
modelo entiende dos operaciones y el intent solo tiene lugar para una, el fallo es
**silencioso**: se carga la primera, el bot contesta "listo" y la segunda no existe
para nadie hasta que no cuadra la caja.

Estas pruebas fijan la red que convierte ese caso en ruidoso: no se carga nada y se
avisa, así el operador se entera en el mismo mensaje en vez de en la caja del día.
"""

from __future__ import annotations

from app.services.ia.contrato import _SYSTEM_PROMPT
from app.services.whatsapp.dispatcher import _CLAVES_DE_LOTE, _lote_no_soportado


# ── La guarda: un lote donde no entra un lote ─────────────────────────

def test_dos_pagos_a_un_intent_de_a_uno_no_cargan_nada() -> None:
    """"Le pagué 500 a Cuello y 300 a Pedro": sale plata por uno y la otra deuda
    queda viva. Frenar el lote entero es la decisión: cargar la primera y perder
    la segunda es exactamente el bug."""
    data = {"pagos": [{"acreedor": "Cuello", "monto": 500}, {"acreedor": "Pedro", "monto": 300}]}
    aviso = _lote_no_soportado("PAGAR_PASIVO", data)
    assert aviso is not None
    assert "2 operaciones" in aviso
    assert "No cargué ninguna" in aviso


def test_avisa_cuantas_operaciones_entendio() -> None:
    data = {"cobros": [{"cliente_nombre": str(i)} for i in range(4)]}
    aviso = _lote_no_soportado("COBRAR_DEUDA_CLIENTE", data)
    assert aviso is not None and "4 operaciones" in aviso


def test_los_intents_con_array_propio_pasan_derecho() -> None:
    """Los seis que sí saben cargar en lote no los toca la guarda."""
    for intent, claves in _CLAVES_DE_LOTE.items():
        data = {claves[0]: [{"nro_cheque": "1"}, {"nro_cheque": "2"}]}
        assert _lote_no_soportado(intent, data) is None, intent


def test_una_sola_operacion_en_lista_no_frena() -> None:
    """Un solo ítem no pierde nada: los handlers leen la raíz igual."""
    data = {"pagos": [{"acreedor": "Cuello", "monto": 500}], "acreedor": "Cuello", "monto": 500}
    assert _lote_no_soportado("PAGAR_PASIVO", data) is None


def test_una_lista_que_no_son_operaciones_no_frena() -> None:
    """Una lista de strings o de números no es un lote de operaciones."""
    data = {"acreedor": "Cuello", "monto": 500, "etiquetas": ["a", "b", "c"]}
    assert _lote_no_soportado("PAGAR_PASIVO", data) is None


def test_las_consultas_no_pasan_por_la_guarda() -> None:
    """No cargan nada, así que no hay operación que perder."""
    data = {"tipo": "CARTERA", "filas": [{"a": 1}, {"b": 2}]}
    assert _lote_no_soportado("CONSULTA", data) is None
    assert _lote_no_soportado("DESCONOCIDO", data) is None


def test_el_lote_de_cheques_en_el_intent_equivocado_frena() -> None:
    """`cheques` en VENDER_CHEQUE no es el array que ese intent sabe leer."""
    data = {"cheques": [{"nro_cheque": "1"}, {"nro_cheque": "2"}]}
    assert _lote_no_soportado("VENDER_CHEQUE", data) is not None


# ── El otro lado: la regla en el prompt ───────────────────────────────

def test_el_prompt_prohibe_elegir_una_de_dos_operaciones() -> None:
    """La guarda solo ve el caso en que el modelo mandó las dos en un array. Si el
    contrato del intent no tiene dónde ponerlas y el modelo elige una, no hay nada
    que detectar: eso lo ataja el prompt."""
    assert "UNA OPERACIÓN POR MENSAJE" in _SYSTEM_PROMPT
    assert "ACLARACION_REQUERIDA" in _SYSTEM_PROMPT


def test_el_prompt_nombra_los_intents_que_si_llevan_lote() -> None:
    """Si el prompt y `_CLAVES_DE_LOTE` se desincronizan, el modelo manda un array
    donde el código lo frena — o peor, deja de mandarlo donde sí se acepta."""
    regla = _SYSTEM_PROMPT.split("16. UNA OPERACIÓN POR MENSAJE")[1][:700]
    for intent, claves in _CLAVES_DE_LOTE.items():
        assert intent in regla, intent
        assert f"`{claves[0]}`" in regla, claves[0]
