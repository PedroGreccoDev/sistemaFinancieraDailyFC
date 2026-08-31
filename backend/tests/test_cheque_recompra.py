"""Recompra: el cheque que se vendió puede volver y comprarse de nuevo (§0028).

Un cheque vendido sigue girando en plaza y por el mismo circuito puede volver a
ofrecérsele al negocio. Cada vuelta es una fila propia, con su compra, su venta y
su caja: no se revierte ni se pisa la pasada anterior, que ocurrió de verdad.

Estilo del proyecto: unitarios puros, sin BD. Se arman instancias de modelo en
memoria y la sesión se stubea con lo mínimo que cada función consulta.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.models import Cheque, ChequeEstado, Cliente
from app.services import cheques as svc
from app.services.exceptions import ValidationError
from app.services.whatsapp.dispatcher import _aviso_recompra, _texto_pasada


# ── Andamios ──────────────────────────────────────────────────────────

def _cliente(nombre: str) -> Cliente:
    return Cliente(id=uuid.uuid4(), nombre=nombre)


def _cheque(
    nro: str = "03789681",
    banco: str | None = "Galicia",
    estado: ChequeEstado = ChequeEstado.EN_CARTERA,
    dia: int = 1,
    monto: str = "1000000.00",
    fecha_pago: date | None = None,
    destino: Cliente | None = None,
) -> Cheque:
    cheque = Cheque(
        id=uuid.uuid4(),
        nro_cheque=nro,
        banco=banco,
        monto=Decimal(monto),
        porcentaje_compra=Decimal("10"),
        fecha_pago=fecha_pago,
        estado=estado,
        created_at=datetime(2026, 8, dia, 12, 0, tzinfo=UTC),
    )
    # `cliente_destino` es una relación: en memoria se asigna directo, sin BD.
    cheque.cliente_destino = destino
    return cheque


class FakeScalars:
    def __init__(self, filas: list[Cheque]) -> None:
        self._filas = filas

    def __iter__(self):
        return iter(self._filas)


class FakeDB:
    """Sesión mínima: `scalars` devuelve tandas programadas, en orden de llamada.

    `resolve_cheque` consulta dos veces (número exacto, después sufijo), así que
    la segunda tanda cubre el caso en que la primera vuelve vacía.
    """

    def __init__(self, *tandas: list[Cheque]) -> None:
        self._tandas = list(tandas)
        self.llamadas = 0

    def scalars(self, *_args, **_kwargs) -> FakeScalars:
        self.llamadas += 1
        if not self._tandas:
            return FakeScalars([])
        return FakeScalars(self._tandas.pop(0))


# ── resolve_cheque: cuál de las pasadas es "el cheque" ─────────────────

def test_con_una_pasada_cerrada_y_otra_en_cartera_elige_la_de_cartera() -> None:
    """El caso central de la recompra.

    Antes esto pedía "indicá el banco para distinguirlos" y el operador quedaba
    trabado: es el MISMO banco en las dos filas, así que no había respuesta
    posible. Lo que las distingue es el estado, no el banco.
    """
    vieja = _cheque(estado=ChequeEstado.VENDIDO, dia=1)
    nueva = _cheque(estado=ChequeEstado.EN_CARTERA, dia=20)
    db = FakeDB([vieja, nueva])

    assert svc.resolve_cheque(db, "03789681") is nueva


def test_con_todas_las_pasadas_cerradas_devuelve_la_ultima() -> None:
    """Ninguna operable: devolver la más reciente hace que el error sea el útil
    ("ese cheque ya está VENDIDO") en vez de una desambiguación sin salida."""
    primera = _cheque(estado=ChequeEstado.VENDIDO, dia=1)
    segunda = _cheque(estado=ChequeEstado.COBRADO, dia=20)
    db = FakeDB([primera, segunda])

    assert svc.resolve_cheque(db, "03789681") is segunda


def test_dos_en_cartera_de_bancos_distintos_sigue_pidiendo_el_banco() -> None:
    """Acá el banco SÍ desambigua: el índice único impide dos filas del mismo
    papel en cartera, así que dos en cartera son cheques realmente distintos."""
    galicia = _cheque(banco="Galicia", dia=1)
    nacion = _cheque(banco="Nación", dia=2)
    db = FakeDB([galicia, nacion])

    with pytest.raises(ValidationError, match="Indicá el banco"):
        svc.resolve_cheque(db, "03789681")


def test_el_banco_indicado_manda_sobre_el_estado() -> None:
    galicia = _cheque(banco="Galicia", estado=ChequeEstado.VENDIDO, dia=1)
    nacion = _cheque(banco="Nación", estado=ChequeEstado.EN_CARTERA, dia=2)
    db = FakeDB([galicia, nacion])

    assert svc.resolve_cheque(db, "03789681", banco="galicia") is galicia


def test_una_sola_pasada_no_cambia_nada() -> None:
    unico = _cheque(estado=ChequeEstado.VENDIDO)
    assert svc.resolve_cheque(FakeDB([unico]), "03789681") is unico


# ── El aviso al operador ──────────────────────────────────────────────

def test_sin_pasadas_anteriores_no_avisa_nada() -> None:
    nuevo = _cheque()
    assert _aviso_recompra(FakeDB([]), nuevo) == []


def test_con_banco_el_aviso_afirma_y_cuenta_la_vuelta() -> None:
    vendido = _cheque(estado=ChequeEstado.VENDIDO, dia=1, destino=_cliente("Benja"))
    nuevo = _cheque(dia=20)
    avisos = _aviso_recompra(FakeDB([vendido]), nuevo)

    assert len(avisos) == 1
    assert "ya pasó por el negocio" in avisos[0]
    assert "2ª vuelta" in avisos[0]
    assert "vendido a Benja" in avisos[0]


def test_sin_banco_pero_con_monto_y_fecha_iguales_tambien_afirma() -> None:
    """El número solo no identifica la lámina, pero número + monto + fecha de pago
    sí: dos cheques distintos prácticamente nunca coinciden en los tres."""
    pago = date(2026, 10, 15)
    vendido = _cheque(banco=None, estado=ChequeEstado.VENDIDO, dia=1, fecha_pago=pago)
    nuevo = _cheque(banco=None, dia=20, fecha_pago=pago)
    avisos = _aviso_recompra(FakeDB([vendido]), nuevo)

    assert "ya pasó por el negocio" in avisos[0]
    assert "monto y fecha de pago" in avisos[0]


def test_sin_banco_y_con_datos_distintos_avisa_como_sospecha() -> None:
    """Mismo número, otro monto: puede ser otra lámina. Se avisa sin afirmar y se
    pide el dato que resolvería la duda."""
    otro = _cheque(banco=None, estado=ChequeEstado.VENDIDO, dia=1, monto="500000.00")
    nuevo = _cheque(banco=None, dia=20, monto="1000000.00")
    avisos = _aviso_recompra(FakeDB([otro]), nuevo)

    assert "Ojo" in avisos[0]
    assert "cargale el banco" in avisos[0]
    assert "ya pasó por el negocio" not in avisos[0]


def test_la_tercera_vuelta_se_cuenta_bien() -> None:
    previas = [
        _cheque(estado=ChequeEstado.VENDIDO, dia=1),
        _cheque(estado=ChequeEstado.COBRADO, dia=10),
    ]
    avisos = _aviso_recompra(FakeDB(previas), _cheque(dia=20))
    assert "3ª vuelta" in avisos[0]


def test_el_aviso_no_lista_mas_de_tres_pasadas() -> None:
    """Con muchas vueltas el comprobante no se puede convertir en un historial."""
    previas = [_cheque(estado=ChequeEstado.VENDIDO, dia=d) for d in range(1, 7)]
    avisos = _aviso_recompra(FakeDB(previas), _cheque(dia=20))

    assert avisos[0].count("vendido el") == 3  # las 3 últimas, no las 6
    assert "7ª vuelta" in avisos[0]            # pero la cuenta es sobre todas


# ── Cómo se cuenta cada pasada ────────────────────────────────────────

def test_la_venta_dice_a_quien() -> None:
    texto = _texto_pasada(_cheque(estado=ChequeEstado.VENDIDO, dia=3, destino=_cliente("Benja")))
    assert texto == "vendido a Benja el 03/08/26"


def test_el_cobro_no_nombra_destino() -> None:
    """Un cheque cobrado se presentó al banco: no hay a quién nombrar, y el
    cliente_destino de una pasada anterior no significa nada acá."""
    texto = _texto_pasada(_cheque(estado=ChequeEstado.COBRADO, dia=3, destino=_cliente("Benja")))
    assert texto == "cobrado el 03/08/26"


def test_el_rechazo_se_cuenta_igual() -> None:
    assert _texto_pasada(_cheque(estado=ChequeEstado.RECHAZADO, dia=3)) == "rechazado el 03/08/26"
