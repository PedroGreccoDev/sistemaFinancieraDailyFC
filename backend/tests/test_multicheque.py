"""Multi-cheque por foto (punto 1 de la reunión 2026-08-06).

Una foto puede traer 4 cheques y el bot debe cargarlos todos. La política ante un
fallo parcial la definió el dueño: **se cargan los válidos y se avisa cuál falló**,
para no obligar a repetir la foto entera por culpa de uno repetido.
"""

from __future__ import annotations

from app.services.ia.claude import INTENTS, _SYSTEM_PROMPT
from app.services.whatsapp.dispatcher import _items_o_uno


# ── Normalización del payload ─────────────────────────────────────────

def test_lista_de_cheques_se_devuelve_entera() -> None:
    data = {"cheques": [{"nro_cheque": "1"}, {"nro_cheque": "2"}, {"nro_cheque": "3"}]}
    assert len(_items_o_uno(data, "cheques")) == 3


def test_un_solo_cheque_en_lista_funciona_igual() -> None:
    assert _items_o_uno({"cheques": [{"nro_cheque": "1"}]}, "cheques") == [{"nro_cheque": "1"}]


def test_formato_viejo_de_un_objeto_sigue_andando() -> None:
    """Compatibilidad: una sesión abierta con historial del formato anterior (campos
    sueltos, sin array) no debe romper a mitad de una conversación."""
    viejo = {"nro_cheque": "00012345", "monto": 100000, "porcentaje_compra": 8}
    assert _items_o_uno(viejo, "cheques") == [viejo]


def test_lista_vacia_cae_al_formato_viejo() -> None:
    # Un array vacío no es "cero cheques": es que el modelo no usó el campo.
    data = {"cheques": [], "nro_cheque": "9"}
    assert _items_o_uno(data, "cheques") == [data]


def test_descarta_elementos_que_no_son_objetos() -> None:
    data = {"cheques": [{"nro_cheque": "1"}, "basura", None]}
    assert _items_o_uno(data, "cheques") == [{"nro_cheque": "1"}]


def test_las_ventas_usan_la_misma_normalizacion() -> None:
    data = {"ventas": [{"nro_cheque": "1"}, {"nro_cheque": "2"}]}
    assert len(_items_o_uno(data, "ventas")) == 2


# ── Contrato del prompt ───────────────────────────────────────────────

def test_el_prompt_pide_todos_los_cheques_de_la_foto() -> None:
    """El riesgo caro no es equivocarse en un dígito: es leer 3 de 4 cheques y que
    el operador dé por cargado el que falta. El prompt tiene que ser explícito."""
    assert "UNA FOTO PUEDE TRAER VARIOS CHEQUES" in _SYSTEM_PROMPT
    assert "cheques: ARRAY" in _SYSTEM_PROMPT
    assert "ventas: ARRAY" in _SYSTEM_PROMPT


def test_el_prompt_resuelve_el_porcentaje_comun() -> None:
    """"Son 4 al 8%" tiene que aplicar 8 a los cuatro, y si no dice el porcentaje
    con varios cheques hay que preguntar en vez de inventar."""
    seccion = _SYSTEM_PROMPT.split("1. REGISTRAR_CHEQUE")[1].split("2. VENDER_CHEQUE")[0]
    assert "aplicá ese mismo a todos" in seccion
    assert "ACLARACION_REQUERIDA" in seccion


def test_registrar_y_vender_siguen_siendo_intents_validos() -> None:
    assert "REGISTRAR_CHEQUE" in INTENTS
    assert "VENDER_CHEQUE" in INTENTS


# ── Ruteo de modelos ──────────────────────────────────────────────────

def test_el_ocr_usa_el_modelo_de_mayor_capacidad() -> None:
    """Leer varios cheques de una foto es la tarea cara de equivocarse del sistema:
    un dígito mal leído es plata mal cargada y NO da ninguna señal de error, así
    que este camino no se abarata ni se le pone escalada (no hay a qué escalar)."""
    from app.services.ia.claude import _MODEL_CONFIRMACION, _MODEL_OCR, _MODEL_TEXTO

    assert _MODEL_OCR == "claude-opus-5"
    # El texto va con un modelo más barato: ahí el error se ve y hay escalada.
    assert _MODEL_TEXTO == "claude-sonnet-5"
    assert _MODEL_OCR != _MODEL_TEXTO
    # Clasificar un "dale" no justifica el modelo caro.
    assert _MODEL_CONFIRMACION == "claude-haiku-4-5"


def _espiar_modelos(monkeypatch, respuesta_por_modelo) -> list[str]:
    """Reemplaza la pasada de extracción y registra a qué modelos se llamó."""
    from app.services.ia import claude as mod

    llamados: list[str] = []

    async def _fake(model: str, effort: str, messages: list) -> object:
        llamados.append(model)
        return respuesta_por_modelo(model)

    monkeypatch.setattr(mod, "_extraer_con_modelo", _fake)
    return llamados


def test_la_foto_va_al_modelo_de_ocr_y_el_texto_al_barato(monkeypatch) -> None:
    import asyncio

    from app.services.ia import claude as mod

    llamados = _espiar_modelos(
        monkeypatch, lambda _m: mod.IntentResult(intent="REGISTRAR_GASTO")
    )

    asyncio.run(mod.extraer_intencion(text="gasté 5000 de nafta", image_bytes=None, history=[]))
    assert llamados == [mod._MODEL_TEXTO]

    llamados.clear()
    asyncio.run(mod.extraer_intencion(text="", image_bytes=b"bytes-de-foto", history=[]))
    assert llamados == [mod._MODEL_OCR]


def test_una_falla_dura_en_texto_escala_al_modelo_capaz(monkeypatch) -> None:
    """None = JSON ilegible, rechazo o error de red. Es la única señal confiable
    de que el modelo barato no pudo."""
    import asyncio

    from app.services.ia import claude as mod

    llamados = _espiar_modelos(
        monkeypatch,
        lambda m: None if m == mod._MODEL_TEXTO else mod.IntentResult(intent="COBRAR_CUOTA"),
    )

    resultado = asyncio.run(
        mod.extraer_intencion(text="juan pagó dos cuotas", image_bytes=None, history=[])
    )

    assert llamados == [mod._MODEL_TEXTO, mod._MODEL_OCR]
    assert resultado.intent == "COBRAR_CUOTA"


def test_pedir_una_aclaracion_no_dispara_escalada(monkeypatch) -> None:
    """Si el operador no dijo el porcentaje, preguntarlo es la respuesta CORRECTA.
    Escalar ahí duplicaría el costo de un caso que funcionó bien."""
    import asyncio

    from app.services.ia import claude as mod

    llamados = _espiar_modelos(
        monkeypatch, lambda _m: mod.IntentResult(intent="ACLARACION_REQUERIDA")
    )

    asyncio.run(mod.extraer_intencion(text="vendí el 681", image_bytes=None, history=[]))

    assert llamados == [mod._MODEL_TEXTO]


def test_el_texto_se_lee_salteando_los_bloques_de_razonamiento() -> None:
    """Con el razonamiento activo, content[0] puede ser un bloque `thinking`:
    leer por índice devolvía basura y rompía el parseo del JSON."""
    from app.services.ia.claude import _texto_de

    class Bloque:
        def __init__(self, tipo: str, texto: str = "") -> None:
            self.type = tipo
            self.text = texto
            self.thinking = texto

    class Respuesta:
        content = [Bloque("thinking", "razonando..."), Bloque("text", '{"intent":"X"}')]

    assert _texto_de(Respuesta()) == '{"intent":"X"}'


def test_sin_bloque_de_texto_devuelve_vacio_en_vez_de_romper() -> None:
    from app.services.ia.claude import _texto_de

    class Respuesta:
        content = []

    assert _texto_de(Respuesta()) == ""
