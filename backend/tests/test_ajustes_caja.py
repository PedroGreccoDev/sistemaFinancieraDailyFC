"""Ajustes manuales de caja (§Ajustes de caja, régimen definido 2026-08-10).

Estilo del proyecto: unitarios puros, sin BD. Se cubren las dos piezas que pueden
descuadrar plata en silencio:

1. El consumo FIFO de un ajuste que **resta** dólares (`consumir_lotes_fifo`), que
   saca stock sin realizar ninguna ganancia.
2. Las reglas de bloqueo al anular un ajuste en dólares, que es cuando devolver o
   sacar stock reescribiría ganancias ya reportadas.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from app.db.models import (
    AjusteCaja,
    AjusteCajaMotivo,
    CajaTipo,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.services.anulacion import _validar_ajuste
from app.services.exceptions import ValidationError
from app.services.movimientos import (
    _orden_ajuste,
    calcular_ganancia_fifo,
    consumir_lotes_fifo,
)


class FakeDB:
    """Sesión mínima: `get` devuelve el objeto programado, `scalar` el resultado."""

    def __init__(self, objeto: object = None, resultado: object = None) -> None:
        self.objeto = objeto
        self.resultado = resultado

    def get(self, *_args, **_kwargs) -> object:
        return self.objeto

    def scalar(self, *_args, **_kwargs) -> object:
        return self.resultado


def _ajuste(
    tipo: CajaTipo,
    moneda: Moneda = Moneda.USD,
    lote_id: uuid.UUID | None = None,
) -> AjusteCaja:
    return AjusteCaja(
        id=uuid.uuid4(),
        fecha=date(2026, 8, 10),
        moneda=moneda,
        tipo=tipo,
        motivo=AjusteCajaMotivo.CORRECCION,
        monto=Decimal("100.00"),
        lote_id=lote_id,
        operador_id="pablo",
    )


def _lote(monto: str, restante: str) -> MovimientoEfectivo:
    return MovimientoEfectivo(
        id=uuid.uuid4(),
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=Decimal(monto),
        cotizacion_aplicada=Decimal("1000"),
        usd_restante=Decimal(restante),
        fecha_operacion=datetime(2026, 8, 1, tzinfo=UTC),
        es_ajuste=True,
    )


# ── Consumo de stock sin ganancia ─────────────────────────────────────

def test_restar_usd_consume_lotes_en_orden_fifo() -> None:
    # Dos lotes de 100 USD; se restan 150 de la caja.
    lotes = [(Decimal("900"), Decimal("100")), (Decimal("1100"), Decimal("100"))]
    consumos = consumir_lotes_fifo(lotes, Decimal("150"))
    # El más viejo se agota primero.
    assert consumos == [Decimal("100"), Decimal("50.00")]


def test_restar_usd_sin_stock_suficiente_lanza_validation_error() -> None:
    lotes = [(Decimal("900"), Decimal("50"))]
    with pytest.raises(ValidationError) as exc:
        consumir_lotes_fifo(lotes, Decimal("80"), accion="restar de la caja")
    assert "restar de la caja" in str(exc.value)


def test_el_consumo_del_ajuste_es_el_mismo_que_el_de_una_venta() -> None:
    """El ajuste usa la misma primitiva: si divergieran, el stock quedaría distinto
    según por dónde se hubieran ido los dólares, que es imposible en la realidad."""
    lotes = [(Decimal("900"), Decimal("100")), (Decimal("1100"), Decimal("100"))]
    _ganancia, consumos_venta = calcular_ganancia_fifo(
        lotes, Decimal("150"), Decimal("1200")
    )
    assert consumir_lotes_fifo(lotes, Decimal("150")) == consumos_venta


# ── Orden dentro de la cadena FIFO ────────────────────────────────────

def test_el_ajuste_se_ubica_al_arranque_de_su_dia() -> None:
    """Un ajuste solo guarda el día. Ubicarlo a las 00:00 lo deja antes de
    cualquier venta de esa jornada y no reordena las ventas entre sí."""
    ajuste = _ajuste(CajaTipo.EGRESO)
    ajuste.created_at = datetime(2026, 8, 10, 15, 30, tzinfo=UTC)
    dia, _creado = _orden_ajuste(ajuste)
    assert dia == datetime(2026, 8, 10, 0, 0, tzinfo=UTC)


def test_ajuste_sin_created_at_no_rompe_el_orden() -> None:
    """Recién insertado, `created_at` lo pone la BD y puede no estar cargado:
    comparar tuplas contra None tiraría TypeError al ordenar la cadena."""
    ajuste = _ajuste(CajaTipo.EGRESO)
    ajuste.created_at = None
    _dia, creado = _orden_ajuste(ajuste)
    assert creado is not None
    # Y la clave completa tiene que seguir siendo comparable con la de otro ajuste.
    otro = _ajuste(CajaTipo.EGRESO)
    otro.created_at = datetime(2026, 8, 10, 9, 0, tzinfo=UTC)
    assert sorted([_orden_ajuste(otro), _orden_ajuste(ajuste)])[0] == _orden_ajuste(ajuste)


# ── Bloqueos al anular ────────────────────────────────────────────────

def test_ajuste_en_pesos_se_anula_siempre() -> None:
    # No toca el stock de dólares, así que no hay cadena FIFO que respetar.
    bloqueo, _ = _validar_ajuste(FakeDB(), _ajuste(CajaTipo.INGRESO, Moneda.ARS))
    assert bloqueo is None


def test_ajuste_que_sumo_usd_con_lote_intacto_se_puede_anular() -> None:
    lote = _lote("100.00", "100.00")
    bloqueo, _ = _validar_ajuste(
        FakeDB(objeto=lote), _ajuste(CajaTipo.INGRESO, lote_id=lote.id)
    )
    assert bloqueo is None


def test_ajuste_que_sumo_usd_ya_vendidos_bloquea() -> None:
    # El lote entró con 100 USD y quedan 40: se vendieron 60.
    lote = _lote("100.00", "40.00")
    bloqueo, _ = _validar_ajuste(
        FakeDB(objeto=lote), _ajuste(CajaTipo.INGRESO, lote_id=lote.id)
    )
    assert bloqueo is not None
    assert "ya fueron vendidos" in bloqueo


def test_ajuste_que_resto_usd_con_ventas_posteriores_bloquea() -> None:
    # FakeDB devuelve una venta posterior a la fecha del ajuste.
    bloqueo, _ = _validar_ajuste(
        FakeDB(resultado=object()), _ajuste(CajaTipo.EGRESO)
    )
    assert bloqueo is not None
    assert "FIFO" in bloqueo


def test_ajuste_que_resto_usd_sin_ventas_posteriores_se_puede_anular() -> None:
    bloqueo, _ = _validar_ajuste(FakeDB(resultado=None), _ajuste(CajaTipo.EGRESO))
    assert bloqueo is None
