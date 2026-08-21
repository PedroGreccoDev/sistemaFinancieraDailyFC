"""El bot tiene que distinguir "me pagó" de "le transfirió a".

Tres frases que se dicen casi igual y mueven la caja de tres maneras distintas:

    "Juan me pagó 500 lucas"          → COBRAR_DEUDA_CLIENTE  (ENTRA plata)
    "le pagué 500 lucas a Pedro"      → pago de pasivo        (SALE plata)
    "Juan le transfirió 500 a Pedro"  → COMPENSAR_DEUDA       (no se mueve)

La diferencia entre la primera y la tercera es un "a Pedro". Y el error no es
simétrico: leer la tercera como la primera mete un ingreso que nunca entró **y
además** deja viva la deuda con Pedro. Descuadra dos cosas de una y no se nota
hasta leer el reporte.

Estilo del proyecto: unitarios puros sobre el contrato del prompt y del
dispatcher, sin llamar al modelo ni tocar la BD.

Ver §Compensación y §Bot.
"""

from __future__ import annotations

from app.services.ia.claude import INTENTS, _SYSTEM_PROMPT


# ── El intent existe de punta a punta ─────────────────────────────────

def test_compensar_deuda_es_un_intent_valido() -> None:
    # Si no está en la lista blanca, el parser lo baja a DESCONOCIDO y el bot
    # responde "no entendí" en vez de compensar.
    assert "COMPENSAR_DEUDA" in INTENTS


def test_el_handler_esta_conectado_al_intent() -> None:
    # Un intent válido que el dispatcher no rutea cae en la respuesta genérica:
    # el operador cree que cargó la operación y no se cargó nada.
    import inspect

    from app.services.whatsapp import dispatcher

    assert hasattr(dispatcher, "_compensar_deuda")
    codigo = inspect.getsource(dispatcher.dispatch)
    assert '"COMPENSAR_DEUDA"' in codigo
    assert "_compensar_deuda" in codigo


# ── El prompt enseña la distinción ────────────────────────────────────

def test_el_prompt_documenta_el_intent() -> None:
    assert "COMPENSAR_DEUDA" in _SYSTEM_PROMPT


def test_el_prompt_contrasta_las_tres_frases_parecidas() -> None:
    # El bloque que las compara es lo único que separa un ingreso real de uno
    # inventado. Si alguien lo saca del prompt, esto falla.
    assert "COBRAR_DEUDA_CLIENTE" in _SYSTEM_PROMPT
    assert "le transfirió" in _SYSTEM_PROMPT


def test_el_prompt_exige_los_dos_nombres() -> None:
    # Sin saber a quién le transfirió no hay contra qué deuda del negocio
    # imputar: el bot tiene que preguntar, no elegir.
    assert "acreedor_nombre" in _SYSTEM_PROMPT


def test_el_prompt_avisa_que_no_mueve_la_caja() -> None:
    assert "NO se mueve la caja" in _SYSTEM_PROMPT


# ── Se puede deshacer desde el chat ───────────────────────────────────

def test_la_compensacion_se_puede_revertir_por_chat() -> None:
    # El dueño pidió que toda operación se pueda deshacer. Si el tipo no está en
    # el prompt, el bot no sabe pedirlo aunque el motor lo soporte.
    assert "COMPENSACION" in _SYSTEM_PROMPT


def test_el_resolutor_de_reversion_conoce_la_compensacion() -> None:
    import inspect

    from app.services.whatsapp import dispatcher

    codigo = inspect.getsource(dispatcher._resolver_para_anular)
    assert '"COMPENSACION"' in codigo
    assert '"compensacion"' in codigo
