"""Que un mensaje entregado dos veces se cargue una sola.

El 2026-08-27 WAHA tenía el webhook cargado por duplicado —la env var global y
la config de la sesión, las dos a la misma URL— y entregaba cada mensaje dos
veces. El webhook no tenía cómo notarlo: dos entregas del mismo mensaje son
indistinguibles de dos pedidos idénticos, así que **la operación se cargaba dos
veces**. Eso se arregló del lado de WAHA, pero la causa que queda viva es el
reintento: WAHA reintenta el webhook que no le contesta a tiempo.

Unitario puro: no hay red ni base. Se mira **qué quedó encolado** en el
`BackgroundTasks`, que es exactamente lo que decide si el mensaje se procesa.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks

from app.api.routes import webhook
from app.services.whatsapp import procesados

TELEFONO = "5493571312648"


@pytest.fixture(autouse=True)
def registro_limpio(monkeypatch):
    """Cada test arranca sin memoria de mensajes y con el bot abierto."""
    procesados.olvidar_todo()
    monkeypatch.setattr(
        webhook, "get_settings", lambda: SimpleNamespace(whatsapp_operator_phone="")
    )
    yield
    procesados.olvidar_todo()


def _entregar(message_id: str, texto: str = "cargá 30 mil de nafta") -> BackgroundTasks:
    """Simula una entrega de WAHA y devuelve lo que quedó encolado."""
    body = {
        "event": "message",
        "payload": {
            "id": message_id,
            "from": f"{TELEFONO}@c.us",
            "fromMe": False,
            "body": texto,
        },
    }
    request = SimpleNamespace(json=_json_de(body))
    tareas = BackgroundTasks()
    asyncio.run(webhook.recibir_mensaje(request, tareas))
    return tareas


def _json_de(body: dict):
    async def _json():
        return body

    return _json


def test_la_segunda_entrega_del_mismo_mensaje_no_se_procesa() -> None:
    """El caso del webhook duplicado: dos POST, un solo mensaje."""
    primera = _entregar("ABC123")
    segunda = _entregar("ABC123")

    assert len(primera.tasks) == 1, "la primera entrega se atiende normal"
    assert segunda.tasks == [], "la segunda es la misma operación: se descarta"


def test_dos_mensajes_distintos_se_procesan_los_dos() -> None:
    """La red no puede comerse mensajes de verdad: el operador manda uno atrás del otro."""
    primero = _entregar("ABC123", "cargá 30 mil de nafta")
    segundo = _entregar("XYZ789", "y 20 mil de comida")

    assert len(primero.tasks) == 1
    assert len(segundo.tasks) == 1


def test_el_mismo_texto_con_otro_id_no_es_un_duplicado() -> None:
    """Repetir una operación a propósito es legítimo: dos gastos iguales el mismo día.

    Lo que identifica al duplicado es el id del mensaje, no lo que dice.
    """
    primero = _entregar("ID-1", "cargá 5 mil de nafta")
    segundo = _entregar("ID-2", "cargá 5 mil de nafta")

    assert len(primero.tasks) == 1
    assert len(segundo.tasks) == 1, "es la segunda carga, no la misma repetida"


def test_sin_id_el_mensaje_pasa_igual() -> None:
    """El modo de falla peligroso, y por eso tiene test propio.

    Si WAHA dejara de mandar el `id`, tratar el string vacío como "ya visto"
    dejaría pasar el primer mensaje y **haría al bot ignorar todos los demás**.
    Perder la protección contra duplicados es aceptable; quedarse mudo no.
    """
    primero = _entregar("")
    segundo = _entregar("")
    tercero = _entregar("")

    assert len(primero.tasks) == 1
    assert len(segundo.tasks) == 1
    assert len(tercero.tasks) == 1


def test_el_registro_no_crece_sin_limite(monkeypatch) -> None:
    """Un flujo anormal de mensajes no puede comerse la memoria del proceso."""
    monkeypatch.setattr(procesados, "_MAX_IDS", 10)

    for i in range(50):
        procesados.ya_procesado(f"id-{i}")

    assert len(procesados._vistos) <= 10
    assert procesados.ya_procesado("id-49") is True, "lo último visto sigue estando"
