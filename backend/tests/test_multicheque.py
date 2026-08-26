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


# ── Fiado de varios cheques (bug del 2026-08-26) ──────────────────────
#
# "Cheques 9460 y 9461 fiado a Lalin al 2,5%": el modelo entendió los dos
# —lo dijo en la confirmación— pero FIAR_CHEQUE solo tenía `nro_cheque`
# suelto, así que al confirmar respondió "Falta el campo 'nro_cheque'" y no
# se cargó ninguno. El alta y la venta ya eran multi; el fiado no.

def test_los_fiados_usan_la_misma_normalizacion() -> None:
    data = {"fiados": [{"nro_cheque": "9460"}, {"nro_cheque": "9461"}]}
    assert len(_items_o_uno(data, "fiados")) == 2


def test_el_fiado_en_formato_viejo_sigue_andando() -> None:
    """Una sesión abierta con historial del contrato anterior (campos sueltos)
    no debe romper a mitad de conversación."""
    viejo = {"nro_cheque": "9460", "cliente_nombre": "Lalin", "porcentaje_venta": 2.5}
    assert _items_o_uno(viejo, "fiados") == [viejo]


def test_el_cliente_y_el_porcentaje_dichos_una_vez_bajan_a_cada_cheque() -> None:
    """"Los fié a Lalin al 2,5%" nombra el cliente y el descuento UNA vez. Si el
    modelo los deja en la raíz, sin herencia el lote entero se cae por un campo
    que el operador sí dictó."""
    data = {
        "fiados": [{"nro_cheque": "9460"}, {"nro_cheque": "9461"}],
        "cliente_nombre": "Lalin",
        "porcentaje_venta": 2.5,
    }
    items = _items_o_uno(
        data, "fiados", heredar=("cliente_nombre", "porcentaje_venta", "banco")
    )
    assert [i["cliente_nombre"] for i in items] == ["Lalin", "Lalin"]
    assert [i["porcentaje_venta"] for i in items] == [2.5, 2.5]


def test_la_herencia_nunca_pisa_lo_que_el_item_ya_dice() -> None:
    """Un porcentaje por cheque ("el 9460 al 2% y el 9461 al 3%") manda sobre
    cualquier valor suelto en la raíz."""
    data = {
        "fiados": [
            {"nro_cheque": "9460", "porcentaje_venta": 2},
            {"nro_cheque": "9461"},
        ],
        "porcentaje_venta": 3,
    }
    items = _items_o_uno(data, "fiados", heredar=("porcentaje_venta",))
    assert [i["porcentaje_venta"] for i in items] == [2, 3]


def test_el_prompt_pide_todos_los_cheques_fiados() -> None:
    assert "fiados: ARRAY" in _SYSTEM_PROMPT
    seccion = _SYSTEM_PROMPT.split("3. FIAR_CHEQUE")[1].split("4. COBRAR_CHEQUE")[0]
    assert "aplican a todos" in seccion
    assert "ACLARACION_REQUERIDA" in seccion


def test_el_fiado_en_lote_carga_los_validos_y_avisa_del_que_falla() -> None:
    """Misma política que el alta y la venta (decisión del dueño, 2026-08-06):
    un cheque ya vendido no puede tirar abajo el resto del lote."""
    from decimal import Decimal

    from app.services.exceptions import ServiceError
    from app.services.whatsapp import dispatcher

    class FakeCheque:
        def __init__(self, nro: str) -> None:
            self.nro_cheque = nro
            self.monto = Decimal("100000")
            self.porcentaje_venta = Decimal("2.5")

    class FakeFiado:
        saldo_pendiente = Decimal("97500")

    class FakeCliente:
        nombre = "Lalin"

    def fake_obj(db, phone, data, msg_at=None):
        if data["nro_cheque"] == "9461":
            raise ServiceError("El cheque ya no está EN_CARTERA")
        return FakeCheque(data["nro_cheque"]), FakeFiado(), FakeCliente()

    original = dispatcher._fiar_un_cheque_obj
    dispatcher._fiar_un_cheque_obj = fake_obj
    try:
        ok, msg = dispatcher._fiar_cheque(
            None,
            "549",
            {
                "fiados": [{"nro_cheque": "9460"}, {"nro_cheque": "9461"}],
                "cliente_nombre": "Lalin",
                "porcentaje_venta": 2.5,
            },
        )
    finally:
        dispatcher._fiar_un_cheque_obj = original

    assert ok is True
    assert "9460" in msg and "Lalin" in msg
    assert "no se pudo(eron) fiar" in msg
    assert "9461" in msg


# ── Cobro y rechazo en lote (revisión del 2026-08-26) ─────────────────
#
# Al banco se va con un fajo y los rebotes vienen de a varios (mismo librador,
# misma cuenta sin fondos). Con un contrato de un solo `nro_cheque`, "cobré el
# 9460 y el 9461" cargaba UNO y perdía el otro EN SILENCIO: el bot contestaba
# "✅ Cheque 9460 COBRADO" y el operador daba los dos por cobrados. El que se
# escapa queda EN CARTERA para siempre y su plata nunca entra a la caja.

def test_los_cobros_y_rechazos_usan_la_misma_normalizacion() -> None:
    assert len(_items_o_uno({"cobros": [{"nro_cheque": "1"}, {"nro_cheque": "2"}]}, "cobros")) == 2
    assert len(_items_o_uno({"rechazos": [{"nro_cheque": "1"}]}, "rechazos")) == 1


def test_cobro_y_rechazo_en_formato_viejo_siguen_andando() -> None:
    viejo = {"nro_cheque": "9460", "banco": "Galicia"}
    assert _items_o_uno(viejo, "cobros") == [viejo]
    assert _items_o_uno(viejo, "rechazos") == [viejo]


def test_el_prompt_pide_todos_los_cheques_cobrados_y_rechazados() -> None:
    assert "cobros: ARRAY" in _SYSTEM_PROMPT
    assert "rechazos: ARRAY" in _SYSTEM_PROMPT


def test_el_cobro_en_lote_no_pierde_ningun_cheque_en_silencio() -> None:
    """El que falla se nombra. Un cheque que no se pudo cobrar y no se informa
    queda EN CARTERA mientras el operador lo da por cobrado."""
    from decimal import Decimal

    from app.services.exceptions import ServiceError
    from app.services.whatsapp import dispatcher

    class FakeCheque:
        def __init__(self, nro: str) -> None:
            self.nro_cheque = nro
            self.banco = "Galicia"
            self.monto = Decimal("100000")

    def fake_uno(db, phone, data, msg_at=None):
        if data["nro_cheque"] == "9461":
            raise ServiceError("El cheque ya está COBRADO")
        return FakeCheque(data["nro_cheque"])

    original = dispatcher._cobrar_un_cheque
    dispatcher._cobrar_un_cheque = fake_uno
    try:
        ok, msg = dispatcher._cobrar_cheque(
            None, "549", {"cobros": [{"nro_cheque": "9460"}, {"nro_cheque": "9461"}]}
        )
    finally:
        dispatcher._cobrar_un_cheque = original

    assert ok is True
    assert "9460" in msg
    assert "9461" in msg and "ya está COBRADO" in msg
    assert "no se pudo(eron) cobrar" in msg


def test_el_medio_de_pago_dicho_una_vez_baja_a_cada_cobro() -> None:
    """"Cobré el 9460 y el 9461, me los transfirieron": el medio se dice una vez
    para todo el fajo. Sin herencia, la plata entraría por la caja equivocada."""
    data = {
        "cobros": [{"nro_cheque": "9460"}, {"nro_cheque": "9461"}],
        "medio_pago": "TRANSFERENCIA",
    }
    items = _items_o_uno(data, "cobros", heredar=("banco", "medio_pago"))
    assert [i["medio_pago"] for i in items] == ["TRANSFERENCIA", "TRANSFERENCIA"]
