"""Cobrarle a un cliente que tiene MÁS DE UN fiado abierto.

Antes esto cortaba con "contactá al administrador para resolverlo desde el panel",
y fiarle varios cheques al mismo cliente es el caso normal —lo dice el fiado en
lote—, así que el aviso se disparaba solo y dejaba el cobro por chat muerto para
ese cliente.

Ahora el cobro se va por **la cuenta general del cliente**: el importe se imputa de
la operación más vieja a la más nueva, cruzando fiados, deudas libres y cuotas. No
hay nada que elegir —el cliente no está pagando *uno* de sus fiados, está pagando
lo que debe— y es la misma regla que ya rige en el cobro consolidado y en los pagos
a un acreedor (decisión del dueño, 2026-08-26).
"""

from __future__ import annotations

from typing import Any

from app.services.ia.contrato import _SYSTEM_PROMPT
from app.services.whatsapp import dispatcher


class _FiadoFalso:
    """Lo mínimo que miran los handlers: un fiado tiene id y saldo."""

    def __init__(self, nro: str) -> None:
        self.id = nro
        self.nro_cheque = nro


def _con_fiados(monkeypatch, cantidad: int) -> dict[str, Any]:
    """Deja al cliente con `cantidad` fiados abiertos y espía a dónde fue el cobro."""
    fueron: dict[str, Any] = {}
    monkeypatch.setattr(
        dispatcher, "_fiados_abiertos",
        lambda db, nombre: [_FiadoFalso(str(i)) for i in range(cantidad)],
    )
    monkeypatch.setattr(
        dispatcher, "_cobrar_deuda_cliente",
        lambda db, data, msg_at=None: (fueron.update(general=data) or (True, "general")),
    )
    monkeypatch.setattr(
        dispatcher, "_cobrar_deuda_cliente_con_cheque",
        lambda db, data, msg_at=None: (fueron.update(general_cheque=data) or (True, "general")),
    )
    return fueron


# ── Efectivo ──────────────────────────────────────────────────────────

def test_con_dos_fiados_el_cobro_va_por_la_cuenta_general(monkeypatch) -> None:
    fueron = _con_fiados(monkeypatch, 2)
    ok, msg = dispatcher._cobrar_fiado_efectivo(
        None, "549", {"cliente_nombre": "Lalin", "monto_cobrado": 400000}
    )
    assert ok is True and msg == "general"
    assert fueron["general"]["monto_cobrado"] == 400000


def test_con_un_solo_fiado_sigue_el_camino_puntual(monkeypatch) -> None:
    """Un fiado solo se salda contra ese fiado: es más preciso y ya andaba."""
    fueron = _con_fiados(monkeypatch, 1)
    llamado: dict[str, Any] = {}
    monkeypatch.setattr(
        dispatcher.svc_fiados, "cobrar_con_efectivo",
        lambda db, fid, payload: (llamado.update(fiado_id=fid), _Cobrado())[1],
    )
    dispatcher._cobrar_fiado_efectivo(
        None, "549", {"cliente_nombre": "Lalin", "monto_cobrado": 100}
    )
    assert "general" not in fueron
    assert llamado["fiado_id"] == "0"


def test_sin_fiados_lo_dice_en_vez_de_mandar_al_panel(monkeypatch) -> None:
    _con_fiados(monkeypatch, 0)
    ok, msg = dispatcher._cobrar_fiado_efectivo(
        None, "549", {"cliente_nombre": "Lalin", "monto_cobrado": 100}
    )
    assert ok is False and "No encontré un fiado abierto" in msg


# ── Con cheque ────────────────────────────────────────────────────────

def test_con_dos_fiados_el_cheque_tambien_va_por_la_cuenta_general(monkeypatch) -> None:
    """El cheque salda por su valor neto, imputado igual que el efectivo."""
    fueron = _con_fiados(monkeypatch, 2)
    ok, msg = dispatcher._cobrar_fiado_con_cheque(
        None, "549",
        {"cliente_nombre": "Ferreyra", "nro_cheque_pago": "9950",
         "monto_cheque": 500000, "porcentaje_compra_cheque": 3},
    )
    assert ok is True and msg == "general"
    assert fueron["general_cheque"]["nro_cheque_pago"] == "9950"


# ── El vuelto, que sí es una pregunta de negocio ──────────────────────

def test_el_vuelto_se_lee_solo_si_es_uno_de_los_dos_modos() -> None:
    """`VueltoModo` es un Literal y no un Enum: no pasa por `_req_enum`. Un valor
    que no reconocemos vuelve None y el servicio pide la aclaración, en vez de
    elegir por el operador qué se hace con plata a favor del cliente."""
    assert dispatcher._vuelto_modo({"vuelto_modo": "SALDAR_EFECTIVO"}) == "SALDAR_EFECTIVO"
    assert dispatcher._vuelto_modo({"vuelto_modo": "queda_debiendo"}) == "QUEDA_DEBIENDO"
    assert dispatcher._vuelto_modo({"vuelto_modo": "lo que sea"}) is None
    assert dispatcher._vuelto_modo({}) is None


# ── El prompt tiene que decir lo mismo que el código ───────────────────

def test_el_prompt_prohibe_preguntar_a_cual_fiado_va() -> None:
    """Si el prompt sigue creyendo que hay que elegir un fiado, el modelo va a
    preguntar por su cuenta aunque el código ya sepa resolverlo."""
    assert "No preguntes a cuál de los fiados va" in _SYSTEM_PROMPT
    assert "No preguntes a cuál de los fiados va." in _SYSTEM_PROMPT


def test_el_prompt_documenta_los_dos_modos_de_vuelto() -> None:
    assert "SALDAR_EFECTIVO" in _SYSTEM_PROMPT
    assert "QUEDA_DEBIENDO" in _SYSTEM_PROMPT


class _Cobrado:
    """Fiado devuelto por el servicio tras un cobro parcial."""

    estado = "ABIERTO"
    saldo_pendiente = 0
