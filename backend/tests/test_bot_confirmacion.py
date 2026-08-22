"""El flujo de confirmación del bot: qué pasa cuando hay algo esperando un "dale".

Lo que se custodia acá es **que un mensaje nunca se tire**. El operador escribe
como habla: confirma y de paso pregunta, corrige un dato sobre la marcha, o
arranca con la operación siguiente sin contestar la anterior. Hasta el
2026-08-21 cualquiera de esas tres cosas cancelaba lo pendiente Y descartaba el
mensaje nuevo, así que había que repetir todo — en los logs de producción se ve
la misma venta reintentada seis veces en tres minutos.

Los casos de abajo son mensajes REALES sacados de esos logs.

Unitario puro: no hay red ni base. Se reemplazan las cuatro puertas de salida
del webhook (el modelo, el dispatcher, la sesión de WhatsApp y el envío) por
registros en memoria.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.api.routes import webhook
from app.services.ia.contrato import INTENTS, IntentResult
from app.services.whatsapp import session as wa_session
from app.services.whatsapp.parser import IncomingMessage

TELEFONO = "5493571312648"


class _Banco:
    """Registra lo que el bot hizo, sin tocar nada de verdad."""

    def __init__(self) -> None:
        self.enviados: list[str] = []
        self.ejecutados: list[IntentResult] = []


@pytest.fixture
def banco(monkeypatch) -> _Banco:
    b = _Banco()
    wa_session.clear_session(TELEFONO)

    async def _send_text(phone, texto, *a, **kw):
        b.enviados.append(texto)

    def _dispatch(db, phone, result, msg_at=None, foto=None):
        b.ejecutados.append(result)
        return True, f"✅ Listo: {result.intent}"

    monkeypatch.setattr(webhook.wa_client, "send_text", _send_text)
    monkeypatch.setattr(webhook.wa_dispatcher, "dispatch", _dispatch)
    monkeypatch.setattr(webhook, "SessionLocal", lambda: SimpleNamespace(close=lambda: None))
    return b


def _responde(monkeypatch, *, veredicto: str, intent: IntentResult) -> None:
    """El modelo contesta esto, sin llamar a ninguna API."""

    async def _clasificar(text):
        return veredicto

    async def _extraer(text, image_bytes, history, media_mime_type="image/jpeg"):
        return intent

    monkeypatch.setattr(webhook.ia_motor, "clasificar_confirmacion", _clasificar)
    monkeypatch.setattr(webhook.ia_motor, "extraer_intencion", _extraer)


def _con_pendiente(intent: str = "VENDER_CHEQUE") -> IntentResult:
    pendiente = IntentResult(intent=intent, confirmacion_requerida=True,
                             respuesta_usuario="¿Confirmás?")
    wa_session.set_pending_intent(TELEFONO, pendiente)
    return pendiente


def _procesar(texto: str) -> None:
    msg = IncomingMessage(phone=TELEFONO, message_type="text", text=texto)
    asyncio.run(webhook._procesar_mensaje(msg, SimpleNamespace()))


# ── Lo que ya andaba y tiene que seguir andando ────────────────────────

def test_un_dale_pelado_confirma(banco, monkeypatch) -> None:
    pendiente = _con_pendiente()
    _responde(monkeypatch, veredicto="confirm", intent=IntentResult())
    _procesar("dale")
    assert banco.ejecutados == [pendiente]
    assert wa_session.get_pending_intent(TELEFONO) is None


def test_un_no_cancela_sin_ejecutar_nada(banco, monkeypatch) -> None:
    _con_pendiente()
    _responde(monkeypatch, veredicto="reject", intent=IntentResult())
    _procesar("no, dejá")
    assert banco.ejecutados == []
    assert "cancelada" in banco.enviados[0].lower()


# ── Los casos reales que se perdían ────────────────────────────────────

def test_una_operacion_nueva_no_se_tira(banco, monkeypatch) -> None:
    """'Vendí cheques 6457 y 6387 al 5%' (22:40 en producción) cancelaba lo
    pendiente y ADEMÁS se descartaba: el operador la tenía que escribir de nuevo."""
    _con_pendiente(intent="REGISTRAR_CHEQUE")
    nueva = IntentResult(intent="VENDER_CHEQUE", respuesta_usuario="Vendido")
    _responde(monkeypatch, veredicto="other", intent=nueva)

    _procesar("Vendí cheques 6457 y 6387 al 5%")

    assert banco.ejecutados == [nueva], "la operación nueva tiene que procesarse"
    assert len(banco.enviados) == 1, "un solo mensaje, no dos"
    assert "NO se cargó" in banco.enviados[0], "y tiene que avisar que lo anterior no se cargó"
    assert "la carga del cheque" in banco.enviados[0], "diciendo QUÉ no se cargó"


def test_una_correccion_no_confirma_la_operacion_mal_cargada(banco, monkeypatch) -> None:
    """'Editar la compra a 3,5' (22:12 en producción). Lo pendiente NO se ejecuta
    —tenía el dato equivocado, que es justo lo que el operador está corrigiendo—
    y la corrección se procesa."""
    pendiente = _con_pendiente(intent="REGISTRAR_CHEQUE")
    correccion = IntentResult(intent="EDITAR_OPERACION", respuesta_usuario="Corregido")
    _responde(monkeypatch, veredicto="other", intent=correccion)

    _procesar("Editar la compra a 3,5")

    assert pendiente not in banco.ejecutados, "confirmar lo que se estaba corrigiendo carga plata mal"
    assert banco.ejecutados == [correccion]


def test_confirmar_y_pedir_otra_cosa_hace_las_dos(banco, monkeypatch) -> None:
    """'Si , decime cuánto queda debiendo' (11:56 en producción): perdía la
    confirmación Y la pregunta."""
    pendiente = _con_pendiente(intent="COBRAR_DEUDA_CLIENTE")
    consulta = IntentResult(intent="CONSULTA", respuesta_usuario="Te paso el saldo")
    _responde(monkeypatch, veredicto="confirm_plus", intent=consulta)

    _procesar("Si , decime cuánto queda debiendo")

    assert banco.ejecutados == [pendiente, consulta], "primero la operación, después la pregunta"
    assert wa_session.get_pending_intent(TELEFONO) is None


def test_una_consulta_suelta_no_cancela_en_silencio(banco, monkeypatch) -> None:
    """'Cuánto le debo a Eula' (12:27 en producción)."""
    _con_pendiente(intent="REGISTRAR_DEUDA")
    consulta = IntentResult(intent="CONSULTA", respuesta_usuario="Te paso las deudas")
    _responde(monkeypatch, veredicto="other", intent=consulta)

    _procesar("Cuánto le debo a Eula")

    assert banco.ejecutados == [consulta]
    assert "la deuda" in banco.enviados[0]


def test_si_lo_nuevo_pide_confirmacion_el_aviso_igual_viaja(banco, monkeypatch) -> None:
    """El aviso no puede perderse solo porque lo nuevo también haya que confirmarlo."""
    _con_pendiente(intent="VENDER_CHEQUE")
    otra = IntentResult(intent="REVERTIR_OPERACION", confirmacion_requerida=True,
                        respuesta_usuario="¿Deshago la nafta?")
    _responde(monkeypatch, veredicto="other", intent=otra)

    _procesar("borra el movimiento de la nafta")

    assert banco.ejecutados == [], "todavía no se ejecuta: espera confirmación"
    assert "NO se cargó" in banco.enviados[0]
    assert "¿Deshago la nafta?" in banco.enviados[0]
    assert wa_session.get_pending_intent(TELEFONO) is otra


# ── El catálogo de nombres ─────────────────────────────────────────────

def test_toda_operacion_de_escritura_tiene_nombre_en_castellano() -> None:
    """El aviso dice QUÉ quedó sin cargar. Un intent de escritura nuevo sin dar
    de alta en `_NOMBRE_INTENT` le mostraría al operador el nombre interno en
    mayúsculas, que no significa nada del otro lado del chat."""
    de_escritura = {
        i for i in INTENTS if IntentResult(intent=i).is_write_operation()
    }
    faltan = sorted(de_escritura - set(webhook._NOMBRE_INTENT))
    assert not faltan, f"sin nombre en castellano: {faltan}"
