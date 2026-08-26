"""Pago consolidado a un acreedor — el espejo del cobro por cliente (§2.c).

Lo que cubre acá es **el vuelto entregando un cheque**, que es lo único que el
panel puede resolver y el bot no: por WhatsApp no hay forma de preguntar qué
hacer con la diferencia, así que sin `vuelto_modo` la entrega se rechaza (esa
rama ya existía). Con el panel pagando por acreedor, esa decisión vuelve a estar
disponible y el cheque que cubre de más tiene que poder entregarse igual.

Estilo `tests/`: unitarios puros, sin BD.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.models import (
    Cheque,
    ChequeEstado,
    Moneda,
    Pasivo,
    PasivoEstado,
)
from app.services import pasivos as svc_pasivos
from app.services.exceptions import ValidationError


# ── Dobles mínimos ───────────────────────────────────────────────────────────

class FakeScalars:
    def __init__(self, items: list[object]) -> None:
        self._items = items

    def __iter__(self):
        return iter(self._items)


class FakeDB:
    """Sesión mínima: devuelve los pasivos programados y junta lo que se agrega."""

    def __init__(self, pasivos: list[Pasivo]) -> None:
        self._pasivos = pasivos
        self.agregados: list[object] = []
        self.commits = 0

    def scalars(self, *_args, **_kwargs) -> FakeScalars:
        return FakeScalars(self._pasivos)

    def add(self, obj: object) -> None:
        self.agregados.append(obj)

    def commit(self) -> None:
        self.commits += 1

    def refresh(self, _obj: object) -> None:
        pass

    def get(self, _modelo, _pk):
        """Sin configuración de apertura no hay corte: todo es operación normal."""
        return None


def _pasivo(concepto: str, saldo: str) -> Pasivo:
    monto = Decimal(saldo)
    return Pasivo(
        id=uuid.uuid4(),
        acreedor="Cuello",
        concepto=concepto,
        monto=monto,
        saldo_pendiente=monto,
        moneda=Moneda.ARS,
        estado=PasivoEstado.PENDIENTE,
    )


def _cheque(monto: str) -> Cheque:
    return Cheque(
        id=uuid.uuid4(),
        nro_cheque="9460",
        banco="Nación",
        monto=Decimal(monto),
        porcentaje_compra=Decimal("10"),
        estado=ChequeEstado.EN_CARTERA,
    )


def _entregar(db: FakeDB, cheque: Cheque, **kwargs):
    return svc_pasivos.cancelar_a_acreedor_con_cheque(
        db,
        acreedor="Cuello",
        cheque=cheque,
        porcentaje_venta=Decimal("0"),
        operador_id="test",
        motivo="Pago de deuda",
        **kwargs,
    )


# ── El reparto, de la más vieja a la más nueva ───────────────────────────────

def test_el_neto_llena_la_deuda_mas_vieja_primero() -> None:
    # Le debe $100.000 (vieja) y $60.000 (nueva); entrega un cheque de $120.000
    # netos: cancela la primera y deja la segunda en $40.000.
    viejo, nuevo = _pasivo("Lote de dólares", "100000"), _pasivo("Cheque comprado", "60000")
    db = FakeDB([viejo, nuevo])

    r = _entregar(db, _cheque("120000"))

    assert viejo.estado == PasivoEstado.CANCELADA
    assert viejo.saldo_pendiente == Decimal("0.00")
    assert nuevo.estado == PasivoEstado.PENDIENTE
    assert nuevo.saldo_pendiente == Decimal("40000.00")
    assert r.cancelados == 1
    assert r.saldo_restante == Decimal("40000.00")


def test_el_cheque_sale_de_cartera() -> None:
    deuda = _pasivo("Lote de dólares", "100000")
    cheque = _cheque("100000")

    _entregar(FakeDB([deuda]), cheque)

    assert cheque.estado == ChequeEstado.VENDIDO


# ── El vuelto: lo que el panel puede y el bot no ─────────────────────────────

def test_sin_vuelto_modo_el_cheque_que_cubre_de_mas_se_rechaza() -> None:
    # Es el camino del bot: por WhatsApp no hay dónde elegir qué hacer con la
    # diferencia, e inventar una de las dos mueve plata que nadie pidió mover.
    db = FakeDB([_pasivo("Lote de dólares", "100000")])

    with pytest.raises(ValidationError, match="cubre de más"):
        _entregar(db, _cheque("150000"))

    assert db.commits == 0


def test_queda_debiendo_crea_el_pasivo_a_favor_por_la_diferencia() -> None:
    # $150.000 netos contra $100.000 de deuda: cancela y quedan $50.000 a favor
    # del cliente, que es un pasivo nuevo y no toca la caja.
    deuda = _pasivo("Lote de dólares", "100000")
    db = FakeDB([deuda])

    r = _entregar(db, _cheque("150000"), vuelto_modo="QUEDA_DEBIENDO")

    assert deuda.estado == PasivoEstado.CANCELADA
    assert r.saldo_restante == Decimal("0.00")
    vueltos = [o for o in db.agregados if isinstance(o, Pasivo)]
    assert len(vueltos) == 1
    assert vueltos[0].monto == Decimal("50000.00")
    assert vueltos[0].moneda == Moneda.ARS


def test_saldar_efectivo_asienta_el_egreso_del_vuelto() -> None:
    # La otra rama: se le devuelve la diferencia, y esa sí sale de la caja.
    db = FakeDB([_pasivo("Lote de dólares", "100000")])

    _entregar(db, _cheque("150000"), vuelto_modo="SALDAR_EFECTIVO")

    # No crea un pasivo a favor: la plata se devolvió.
    assert not [o for o in db.agregados if isinstance(o, Pasivo)]
    lineas = [o for o in db.agregados if type(o).__name__ == "MovimientoCaja"]
    assert len(lineas) == 1
    assert lineas[0].monto == Decimal("50000.00")


def test_el_centavo_de_redondeo_no_es_un_vuelto() -> None:
    # Un neto un centavo por encima del total se tolera desde siempre: se salda
    # todo y ese resto se pierde. Con `vuelto_modo` no puede convertirse en un
    # pasivo de $0,01 a favor del cliente.
    deuda = _pasivo("Lote de dólares", "100000")
    db = FakeDB([deuda])

    _entregar(db, _cheque("100000.01"), vuelto_modo="QUEDA_DEBIENDO")

    assert deuda.estado == PasivoEstado.CANCELADA
    assert [o for o in db.agregados if isinstance(o, Pasivo)] == []


# ── El chat y el panel tienen que decir lo mismo ─────────────────────────────

def test_la_consulta_del_bot_agrupa_con_el_mismo_criterio_que_el_pago() -> None:
    """Un acreedor cargado con otra mayúscula es el MISMO acreedor.

    `_resolver_acreedor` y `cargar_pasivos_acreedor` normalizan (trim +
    minúsculas) y el panel agrupa igual, así que la consulta tiene que hacerlo
    también: si no, el chat lista dos renglones chicos donde el panel muestra uno
    grande y el pago los junta. El operador lee que le debe menos.
    """
    from app.services.whatsapp import dispatcher

    pasivos = [_pasivo("Lote de dólares", "100000"), _pasivo("Vuelto cheque", "63500")]
    pasivos[1].acreedor = "  cuello "

    original = dispatcher._pasivos_pendientes
    dispatcher._pasivos_pendientes = lambda _db: pasivos
    try:
        texto = dispatcher._consulta_pasivos(None, None, None, {}, "TODO")
    finally:
        dispatcher._pasivos_pendientes = original

    # Un solo renglón de acreedor, por el total de las dos deudas.
    assert texto.count("👤") == 1
    assert "2 deudas" in texto
    assert "cuello" not in texto  # se muestra con el nombre tal como se escribió
