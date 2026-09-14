"""Una foto de cheques no dice qué operación es: lo dice el verbo del operador.

El caso real (2026-09-14): el operador mandó la foto de dos cheques con
*"Kiosco me pagó con estos cheques"*. El bot leyó los dos bien y preguntó
*"¿con qué porcentaje los tomo?"*; el operador contestó el porcentaje y la
operación entró como **compra de cartera**. Eso saca de la caja plata que nunca
salió y, además, deja viva la deuda del Kiosco: descuadra dos cosas de una y no
da ninguna señal hasta que no cierra la caja.

Dos agujeros, uno por test:

1. **El prompt no contrastaba las dos frases.** Con foto, el §1 es un imán: "el
   operador manda foto(s) de cheque" → alta. Nada decía que *"me pagó con
   estos"* es un cobro (§9).
2. **La foto no sobrevivía a la pregunta.** El turno siguiente es texto, así que
   lo atendía el modelo de texto **sin la imagen**, reconstruyendo los cheques y
   la operación desde lo que hubiera quedado escrito en el historial — y lo que
   había quedado escrito era una pregunta redactada como compra ("los tomo").

Unitario puro: no hay red ni base. Igual que `test_bot_confirmacion.py`, se
reemplazan las puertas de salida del webhook por registros en memoria.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api.routes import webhook
from app.services.ia.contrato import IntentResult, _SYSTEM_PROMPT as SYSTEM_PROMPT
from app.services.whatsapp import session as wa_session
from app.services.whatsapp.parser import IncomingMessage

TELEFONO = "5493571312648"
_SETTINGS = SimpleNamespace(confirmacion_umbral_ars=20_000_000, confirmacion_umbral_usd=15_000)


# ── El prompt: qué separa la compra del cobro ────────────────────────────────

def test_el_prompt_contrasta_comprar_con_recibir_como_pago():
    """Las dos frases se dicen con la misma foto delante y mueven la caja al revés."""
    assert "me pagó con estos cheques" in SYSTEM_PROMPT
    assert "NO ES SIEMPRE UNA COMPRA" in SYSTEM_PROMPT
    # Y dice por qué importa: el error no es simétrico.
    assert "nunca salió" in SYSTEM_PROMPT
    assert "deja viva la deuda" in SYSTEM_PROMPT


def test_el_prompt_avisa_que_el_porcentaje_no_desempata():
    """Preguntar solo el porcentaje deja la duda viva para el turno siguiente.

    Es exactamente lo que pasó: la pregunta se contesta igual ("al 5%") sea una
    compra o un cobro, así que no aporta nada para decidir cuál era.
    """
    assert "EL PORCENTAJE NO DESEMPATA" in SYSTEM_PROMPT


def test_el_prompt_manda_reconstruir_tambien_el_INTENT():
    """El dato que falta se le agrega a la operación que el operador ya dijo.

    Sin esta regla, el turno del porcentaje vuelve a elegir intent desde cero
    con un historial que solo tiene la pregunta del bot — redactada como compra.
    """
    assert "EL INTENT TAMBIÉN SE RECONSTRUYE" in SYSTEM_PROMPT
    assert "NOMBRÁ LA OPERACIÓN" in SYSTEM_PROMPT


# ── El webhook: la foto sobrevive a la pregunta, y solo un turno ─────────────

class _Banco:
    def __init__(self) -> None:
        self.vistas: list[bytes | None] = []   # lo que vio el modelo en cada turno
        self.fotos_dispatch: list[tuple[bytes, str] | None] = []


@pytest.fixture
def banco(monkeypatch) -> _Banco:
    b = _Banco()
    wa_session.clear_session(TELEFONO)
    respuestas: list[IntentResult] = []

    async def _send_text(phone, texto, *a, **kw):
        pass

    def _dispatch(db, phone, result, msg_at=None, foto=None):
        b.fotos_dispatch.append(foto)
        return result.intent != "ACLARACION_REQUERIDA", f"✅ {result.intent}"

    async def _extraer(text, image_bytes, history, media_mime_type="image/jpeg"):
        b.vistas.append(image_bytes)
        return respuestas.pop(0)

    monkeypatch.setattr(webhook.wa_client, "send_text", _send_text)
    monkeypatch.setattr(webhook.wa_dispatcher, "dispatch", _dispatch)
    monkeypatch.setattr(webhook.ia_motor, "extraer_intencion", _extraer)
    monkeypatch.setattr(webhook, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    b.respuestas = respuestas
    return b


def _procesar(texto: str, *, foto: bytes | None = None) -> None:
    msg = IncomingMessage(
        phone=TELEFONO, message_type="image" if foto else "text", text=texto
    )
    if foto:
        msg.media_bytes = foto
        msg.media_mime_type = "image/jpeg"
    asyncio.run(webhook._procesar_mensaje(msg, _SETTINGS))


def _aclaracion() -> IntentResult:
    return IntentResult(
        intent="ACLARACION_REQUERIDA",
        data={"pregunta": "¿A qué % se los recibís por lo que te debe?"},
        respuesta_usuario="¿A qué % se los recibís por lo que te debe?",
    )


def _cobro() -> IntentResult:
    return IntentResult(intent="COBRAR_FIADO_CON_CHEQUE", data={"cliente_nombre": "Kiosco"})


def test_la_foto_vuelve_en_el_turno_que_contesta_la_aclaracion(banco):
    """Contestar "al 5%" tiene que llegar al modelo CON la imagen.

    Si no, el porcentaje lo resuelve el camino de texto reconstruyendo los
    cheques de memoria — y encima sin la foto que después se guarda con el
    cheque.
    """
    banco.respuestas.extend([_aclaracion(), _cobro()])

    _procesar("Kiosco me pagó con estos cheques", foto=b"los-dos-cheques")
    _procesar("los dos al 5%")

    assert banco.vistas == [b"los-dos-cheques", b"los-dos-cheques"]
    # Y llega al dispatch, así que el cheque que se cargue queda con su foto.
    assert banco.fotos_dispatch[-1] == (b"los-dos-cheques", "image/jpeg")


def test_la_foto_retomada_vale_por_un_solo_turno(banco):
    """Arrastrarla más allá mandaría un "cuánto hay en caja" por el camino del OCR."""
    banco.respuestas.extend([_aclaracion(), _cobro(), _cobro()])

    _procesar("Kiosco me pagó con estos cheques", foto=b"los-dos-cheques")
    _procesar("los dos al 5%")
    _procesar("cuánto hay en caja")

    assert banco.vistas[-1] is None


def test_cobrar_deuda_cliente_con_papeles_va_por_el_camino_del_cheque(monkeypatch):
    """`COBRAR_DEUDA_CLIENTE` también puede traer `cheques`, y no son efectivo.

    El prompt lo habilita (regla 16) y `_CLAVES_DE_LOTE` lo lista, pero el
    handler de efectivo no los miraba: los papeles se perdían y, con un
    `monto_cobrado` estimado por el modelo, la deuda bajaba como si hubiera
    entrado plata que nunca entró. Vale para las dos bolsas —cuenta y crédito—:
    cuál de las dos es lo decide `_bolsa_y_moneda` del otro lado.
    """
    from app.services.whatsapp import dispatcher

    llamadas: list[dict] = []
    monkeypatch.setattr(
        dispatcher,
        "_cobrar_deuda_cliente_con_cheque",
        lambda db, data, msg_at=None: (llamadas.append(data), (True, "✅"))[1],
    )

    dispatcher._cobrar_deuda_cliente(
        None,
        {
            "cliente_nombre": "Kiosco",
            "monto_cobrado": 1_507_650,   # el modelo lo estimó: no es plata que entró
            "destino": "PRESTAMO",
            "cheques": [{"nro_cheque": "68771912", "monto": 687_000, "porcentaje_compra": 5}],
        },
    )

    assert llamadas and llamadas[0]["destino"] == "PRESTAMO"


def test_una_foto_nueva_no_se_mezcla_con_la_retomada(banco):
    """El mensaje que trae su propia foto manda: la vieja se descarta, no se apila."""
    banco.respuestas.extend([_aclaracion(), _aclaracion(), _cobro()])

    _procesar("Kiosco me pagó con estos cheques", foto=b"primera")
    _procesar("y estos otros", foto=b"segunda")
    _procesar("los dos al 5%")

    assert banco.vistas == [b"primera", b"segunda", b"segunda"]
