"""Consulta de historial de un cheque: "¿este papel pasó por acá y de quién vino?"

El operador le vendió un cheque a un cliente, el cheque rebotó y el cliente
vuelve al mostrador con el papel en la mano. Lo que el operador necesita en ese
momento es **a quién reclamarle**, que es de quién recibió el papel. Manda la
foto, pregunta, y el bot le contesta con la operación de compra: vendedor,
fecha, porcentaje y monto _(caso de uso del dueño, 2026-09-22)_.

Lo que estos tests custodian:

1. **Que sea lectura y solo lectura.** La misma foto, con otro verbo, es una
   compra que saca plata de la caja. Una pregunta nunca puede terminar en un
   alta.
2. **Que no conteste que no cuando la respuesta es sí.** Un banco que el OCR leyó
   distinto, un número resuelto por los últimos dígitos o una carga anulada no
   pueden hacer desaparecer un cheque que el negocio sí tuvo: se muestra igual,
   con la advertencia al lado.
3. **Que el vendedor esté siempre.** Es el único dato por el que se hace la
   consulta.

Estilo del proyecto: unitarios puros sobre el contrato del prompt y del
dispatcher. Sin BD ni llamadas al modelo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Cliente,
    Moneda,
    MovimientoCaja,
)
from app.services import cheques as svc_cheques
from app.services.exceptions import ValidationError
from app.services.ia.claude import _SYSTEM_PROMPT
from app.services.ia.contrato import IntentResult
from app.services.whatsapp.dispatcher import (
    _CONSULTAS,
    _cheques_consultados,
    _consulta,
    _consulta_cheque,
    _historial_de_un_cheque,
)


# ── Andamios ──────────────────────────────────────────────────────────

def _cliente(nombre: str) -> Cliente:
    return Cliente(id=uuid.uuid4(), nombre=nombre)


def _cheque(
    nro: str = "03789681",
    banco: str | None = "Galicia",
    estado: ChequeEstado = ChequeEstado.EN_CARTERA,
    origen: Cliente | None = None,
    destino: Cliente | None = None,
    dia: int = 1,
    monto: str = "1000000.00",
    pct_compra: str = "10",
    pct_venta: str | None = None,
    ganancia: str = "0.00",
    anulado: bool = False,
    carga_inicial: bool = False,
    abonado: str | None = None,
) -> Cheque:
    cheque = Cheque(
        id=uuid.uuid4(),
        nro_cheque=nro,
        banco=banco,
        monto=Decimal(monto),
        porcentaje_compra=Decimal(pct_compra),
        porcentaje_venta=None if pct_venta is None else Decimal(pct_venta),
        monto_abonado=None if abonado is None else Decimal(abonado),
        ganancia=Decimal(ganancia),
        fecha_pago=date(2026, 9, 30),
        estado=estado,
        es_carga_inicial=carga_inicial,
        created_at=datetime(2026, 8, dia, 12, 0, tzinfo=UTC),
        ultimo_evento_manual_at=datetime(2026, 8, dia + 5, 12, 0, tzinfo=UTC),
    )
    # Relaciones: en memoria se asignan directo, sin BD.
    cheque.cliente_origen = origen
    cheque.cliente_destino = destino
    if anulado:
        cheque.anulado_at = datetime(2026, 8, dia + 1, 12, 0, tzinfo=UTC)
    return cheque


def _mov(cheque: Cheque, categoria: CajaCategoria, dia: int) -> MovimientoCaja:
    return MovimientoCaja(
        id=uuid.uuid4(),
        fecha=date(2026, 8, dia),
        moneda=Moneda.ARS,
        tipo=CajaTipo.EGRESO,
        categoria=categoria,
        monto=Decimal("900000.00"),
        referencia_tipo="cheque",
        referencia_id=cheque.id,
    )


class FakeScalars:
    def __init__(self, filas: list) -> None:
        self._filas = filas

    def __iter__(self):
        return iter(self._filas)


class FakeDB:
    """Sesión mínima: `scalars` devuelve tandas programadas, en orden de llamada.

    El orden de consulta es siempre el mismo: primero el número exacto, después
    el sufijo si el exacto vino vacío, y al final el libro de caja.
    """

    def __init__(self, *tandas: list) -> None:
        self._tandas = list(tandas)

    def scalars(self, *_args, **_kwargs) -> FakeScalars:
        return FakeScalars(self._tandas.pop(0) if self._tandas else [])


# ── El tipo existe de punta a punta ───────────────────────────────────

def test_el_tipo_cheque_tiene_handler_y_esta_en_el_prompt() -> None:
    # Sin handler, el modelo pide un tipo que el dispatcher no conoce y el bot
    # contesta "no sé qué consultar" a una pregunta perfectamente válida.
    assert _CONSULTAS["CHEQUE"] is _consulta_cheque
    assert "* CHEQUE" in _SYSTEM_PROMPT


def test_consultar_un_cheque_no_escribe_ni_limpia_la_sesion() -> None:
    # Es lectura y nada más que lectura (decisión del dueño): una consulta que
    # se marcara como escritura pediría confirmación para mostrar un dato.
    assert not IntentResult(intent="CONSULTA").is_write_operation()
    limpiar, _ = _consulta(FakeDB([], []), {"tipo": "CHEQUE", "nro_cheque": "1"})
    assert limpiar is False


# ── Qué papeles preguntó ──────────────────────────────────────────────

def test_toma_el_cheque_de_la_raiz() -> None:
    assert _cheques_consultados({"nro_cheque": "681", "banco": "Galicia"}) == [
        ("681", "Galicia")
    ]


def test_toma_todos_los_cheques_del_array() -> None:
    # Una foto puede traer varios papeles y el operador pregunta por la foto
    # entera: contestar por el primero deja los otros sin respuesta.
    data = {"cheques": [{"nro_cheque": "111"}, {"nro_cheque": "222", "banco": "Nación"}]}
    assert _cheques_consultados(data) == [("111", None), ("222", "Nación")]


def test_no_repite_el_mismo_cheque_dos_veces() -> None:
    data = {"cheques": [{"nro_cheque": "111"}, {"nro_cheque": "111"}]}
    assert _cheques_consultados(data) == [("111", None)]


def test_sin_numero_no_hay_nada_que_buscar() -> None:
    assert _cheques_consultados({"tipo": "CHEQUE"}) == []


def test_sin_numero_pide_el_dato_en_vez_de_romper() -> None:
    salida = _consulta_cheque(FakeDB(), date.today(), date.today(), {}, "TODO")
    assert "¿De qué cheque?" in salida


# ── La búsqueda ───────────────────────────────────────────────────────

def test_la_busqueda_exige_un_numero() -> None:
    with pytest.raises(ValidationError):
        svc_cheques.historial_por_numero(FakeDB(), "")


def test_si_el_numero_exacto_no_esta_busca_por_sufijo() -> None:
    # El operador nombra el cheque por los últimos dígitos también cuando
    # pregunta, no solo cuando opera.
    viejo = _cheque()
    db = FakeDB([], [viejo])
    assert svc_cheques.historial_por_numero(db, "9681") == [viejo]


# ── La respuesta ──────────────────────────────────────────────────────

def test_un_cheque_que_nunca_paso_se_contesta_que_no() -> None:
    salida = _historial_de_un_cheque(FakeDB([], []), "03789681", "Galicia")
    assert salida.startswith("❌ *No,")
    assert "03789681" in salida


def test_la_respuesta_trae_al_vendedor_la_fecha_y_el_porcentaje() -> None:
    """El renglón por el que existe la consulta.

    El cliente vuelve con el cheque rebotado: sin el nombre del que se lo vendió
    al operador, la respuesta no sirve para nada."""
    cheque = _cheque(origen=_cliente("Kiosco Pedro"), estado=ChequeEstado.VENDIDO,
                     destino=_cliente("Benja"), pct_venta="3", ganancia="70000.00")
    db = FakeDB([cheque], [_mov(cheque, CajaCategoria.COMPRA_CHEQUE, 12)])

    salida = _historial_de_un_cheque(db, "03789681", "Galicia")

    assert salida.startswith("✅ *Sí,")
    assert "*Kiosco Pedro*" in salida          # a quién reclamarle
    assert "12/08/26" in salida                # cuándo entró
    assert "al 10%" in salida                  # a qué porcentaje
    assert "$900.000,00" in salida             # cuánto pagó por él
    assert "*Benja*" in salida                 # y a quién se lo vendió


def test_el_que_sigue_en_cartera_lo_dice() -> None:
    cheque = _cheque(origen=_cliente("Kiosco"))
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", None)
    assert "Sigue en cartera" in salida


def test_el_entregado_a_un_acreedor_nombra_al_acreedor() -> None:
    # Esa salida no mueve un peso: sin este renglón no queda registro de quién
    # se llevó el papel.
    cheque = _cheque(origen=_cliente("Kiosco"), estado=ChequeEstado.VENDIDO)
    cheque.acreedor_destino = "Fernando"
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", None)
    assert "*Fernando*" in salida
    assert "deuda tuya" in salida


def test_la_carga_inicial_dice_que_no_hay_vendedor() -> None:
    # No tiene vendedor ni compra: estaba en cartera desde antes del sistema.
    # Inventar un nombre ahí sería mandar al operador a reclamarle a cualquiera.
    cheque = _cheque(carga_inicial=True, estado=ChequeEstado.VENDIDO)
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", None)
    assert "no hay vendedor cargado" in salida


def test_el_comprado_a_deber_muestra_lo_que_quedo_debiendo() -> None:
    cheque = _cheque(origen=_cliente("Kiosco"), abonado="500000.00")
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", None)
    assert "le pagaste $500.000,00" in salida
    assert "debiendo $400.000,00" in salida


# ── Lo encontrado no es exactamente lo preguntado ─────────────────────

def test_el_anulado_se_muestra_igual_y_avisa() -> None:
    # Decisión del dueño: si preguntás por el papel, que esa carga se haya
    # anulado es parte de la respuesta, no un motivo para decir que no existió.
    cheque = _cheque(origen=_cliente("Kiosco"), anulado=True)
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", None)
    assert salida.startswith("✅ *Sí,")
    assert "anulada" in salida
    assert "*Kiosco*" in salida


def test_si_el_banco_no_coincide_lo_muestra_con_la_advertencia() -> None:
    # El banco que dicta un OCR es de lo primero que sale mal: esconder el
    # cheque por eso deja al operador creyendo que nunca lo tuvo.
    cheque = _cheque(banco="Banco Nación", origen=_cliente("Kiosco"))
    salida = _historial_de_un_cheque(FakeDB([cheque], []), "03789681", "Galicia")
    assert salida.startswith("✅ *Sí,")
    assert "El que tengo es de Banco Nación, no de Galicia" in salida


def test_si_se_resolvio_por_sufijo_avisa_el_numero_completo() -> None:
    cheque = _cheque(nro="03789681", origen=_cliente("Kiosco"))
    salida = _historial_de_un_cheque(FakeDB([], [cheque], []), "9681", None)
    assert "el número completo es 03789681" in salida


def test_las_pasadas_se_muestran_todas_y_numeradas() -> None:
    """Con la recompra un papel vuelve, y cada vuelta tiene su propio vendedor.

    Quedarse con una sola mandaría a reclamarle al vendedor equivocado."""
    primera = _cheque(origen=_cliente("Kiosco"), estado=ChequeEstado.VENDIDO, dia=1)
    segunda = _cheque(origen=_cliente("Pedro"), dia=20)
    db = FakeDB([primera, segunda], [])

    salida = _historial_de_un_cheque(db, "03789681", "Galicia")

    assert "1ª vuelta" in salida and "2ª vuelta" in salida
    assert "*Kiosco*" in salida and "*Pedro*" in salida


# ── El prompt: la foto con una pregunta NO es una carga ───────────────

def test_el_prompt_manda_la_foto_con_pregunta_a_la_consulta() -> None:
    # Es el error caro: la misma foto, leída como compra, saca de la caja plata
    # que nunca salió.
    assert "CONSULTA con tipo CHEQUE" in _SYSTEM_PROMPT
    assert "Una pregunta NUNCA\n             es una compra" in _SYSTEM_PROMPT


def test_el_prompt_no_pide_porcentaje_para_una_consulta() -> None:
    # Sin esto el bot contesta "¿a qué % lo compraste?" a alguien que preguntó
    # otra cosa, y la consulta nunca llega a correr.
    assert "NUNCA lleva porcentaje: no lo pidas" in _SYSTEM_PROMPT


def test_el_prompt_suelta_la_carga_pendiente_ante_una_pregunta() -> None:
    # El flujo real: foto sola → el bot pregunta el porcentaje → el operador
    # contesta con la pregunta. La reconstrucción multi-turno tiene que ceder
    # ahí, o el bot insiste con el porcentaje para siempre.
    assert "UNA PREGUNTA NO ES LA RESPUESTA A TU PREGUNTA" in _SYSTEM_PROMPT
