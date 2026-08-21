"""Todo dólar que entra o sale mueve el stock, no solo la compra/venta (§Stock de dólares).

La caja USD dice cuántos dólares hay; el **stock** son los lotes con su costo, y
es contra ese costo que se calcula la ganancia FIFO al venderlos. Hasta la
migración `0025` las dos cosas divergían: cinco salidas de dólares —otorgar una
deuda o un préstamo en USD, un gasto en USD, pagar un pasivo en USD— no consumían
lotes, y tres entradas —cobrar una cuota, un fiado o una deuda en USD— no creaban
ninguno.

Ninguno de los dos lados avisaba. Los dólares que salían seguían contando como
vendibles y prestaban su costo a una ganancia futura sin respaldo; los que
entraban no se podían vender aunque estuvieran en la mano.

Estilo del proyecto: unitarios puros, sin BD. Lo que se ejercita acá es el
contrato —qué se representa como movimiento de stock, con qué marca, y qué
catálogos tienen que estar completos—; el recorrido contra una base real se
verificó aparte.
"""

from __future__ import annotations

import inspect
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Moneda, MovimientoEfectivoTipo
from app.services import stock_usd
from app.services.anulacion import _ORIGENES_STOCK, _ENTIDADES
from app.services.exceptions import ValidationError
from app.services.movimientos import _reimputar_fifo, consumir_lotes_fifo


class FakeDB:
    """Sesión mínima: junta lo agregado y lo borrado, sin tocar una base."""

    def __init__(self, existentes: list | None = None) -> None:
        self.agregados: list = []
        self.borrados: list = []
        self.existentes = existentes or []

    def add(self, obj) -> None:
        self.agregados.append(obj)

    def delete(self, obj) -> None:
        self.borrados.append(obj)

    def flush(self) -> None:
        pass

    def scalars(self, _stmt):
        return self.existentes


# ── La cotización NUNCA se asume ──────────────────────────────────────

def test_sin_cotizacion_no_entra_stock() -> None:
    # Es la regla 1 del negocio: el sistema jamás inventa un precio de dólar. Sin
    # costo esos dólares no se podrían vender, y descubrirlo el día de la venta es
    # tarde — para entonces nadie se acuerda a cuánto estaba.
    with pytest.raises(ValidationError):
        stock_usd.ingresar(
            FakeDB(), monto=Decimal("100"), cotizacion=None, fecha=None,
            origen_tipo="fiado_cobro", origen_id=None, detalle="x",
        )


def test_una_cotizacion_en_cero_tampoco_sirve() -> None:
    with pytest.raises(ValidationError):
        stock_usd.ingresar(
            FakeDB(), monto=Decimal("100"), cotizacion=Decimal("0"), fecha=None,
            origen_tipo="fiado_cobro", origen_id=None, detalle="x",
        )


# ── Cómo se representa cada movimiento de stock ───────────────────────

def test_lo_que_entra_es_una_compra_con_su_costo() -> None:
    db = FakeDB()
    lote = stock_usd.ingresar(
        db, monto=Decimal("300"), cotizacion=Decimal("1300"), fecha=None,
        origen_tipo="fiado_cobro", origen_id=None, detalle="cobro",
    )
    assert lote.tipo == MovimientoEfectivoTipo.COMPRA
    assert lote.moneda == Moneda.USD
    assert lote.cotizacion_aplicada == Decimal("1300")
    # Lote intacto: nada consumido todavía.
    assert lote.usd_restante == Decimal("300.00")


def test_lo_que_sale_es_una_venta_sin_ganancia() -> None:
    db = FakeDB()
    salida = stock_usd.egresar(
        db, monto=Decimal("50"), fecha=None,
        origen_tipo="gasto", origen_id=None, detalle="gasto",
    )
    assert salida.tipo == MovimientoEfectivoTipo.VENTA
    # No hubo precio de venta: esos dólares no se vendieron, se fueron. Contar una
    # ganancia acá inventaría plata que nadie ganó.
    assert salida.ganancia == Decimal("0.00")
    assert salida.usd_restante == Decimal("0.00")


def test_todo_movimiento_de_stock_va_marcado_es_ajuste() -> None:
    # `es_ajuste` es la marca de "stock que se movió sin una operación de divisas
    # detrás". De ella dependen tres cosas: que NO asiente caja (ya la mueve la
    # operación de negocio), que no figure como una compra/venta en el listado de
    # Divisas, y que el FIFO lo consuma sin calcularle ganancia.
    db = FakeDB()
    entra = stock_usd.ingresar(
        db, monto=Decimal("10"), cotizacion=Decimal("1000"), fecha=None,
        origen_tipo="deuda_simple_cobro", origen_id=None, detalle="x",
    )
    sale = stock_usd.egresar(
        db, monto=Decimal("10"), fecha=None,
        origen_tipo="deuda_simple", origen_id=None, detalle="x",
    )
    assert entra.es_ajuste and sale.es_ajuste


def test_el_movimiento_recuerda_de_que_operacion_salio() -> None:
    # Sin el par origen_tipo/origen_id, anular el gasto o el cobro que lo generó no
    # podría encontrarlo y esos dólares quedarían para siempre en la cadena.
    db = FakeDB()
    sale = stock_usd.egresar(
        db, monto=Decimal("10"), fecha=None,
        origen_tipo="pasivo_pago", origen_id="id-del-pasivo", detalle="x",
    )
    assert (sale.origen_tipo, sale.origen_id) == ("pasivo_pago", "id-del-pasivo")


# ── Orden en la cadena FIFO ───────────────────────────────────────────

def test_lo_de_hoy_se_ubica_con_la_hora_real() -> None:
    # Fechar al arranque del día un cobro hecho a la tarde lo pondría ANTES de la
    # compra de la mañana: una venta posterior saldría del lote equivocado y la
    # ganancia se calcularía contra un costo que no correspondía.
    momento = stock_usd._momento_operativo(None)
    assert (momento.hour, momento.minute) != (0, 0) or momento.second != 0


def test_de_una_fecha_pasada_solo_se_sabe_el_dia() -> None:
    momento = stock_usd._momento_operativo(date(2020, 5, 4))
    assert momento.date() == date(2020, 5, 4)
    assert (momento.hour, momento.minute, momento.second) == (0, 0, 0)


# ── La reimputación tiene que ver estos movimientos ───────────────────

def test_el_fifo_consume_las_salidas_de_stock_sin_ganancia() -> None:
    # Si `_reimputar_fifo` no las tratara como consumo sin ganancia, les calcularía
    # una contra la `cotizacion_aplicada` de relleno (1) y daría una pérdida enorme.
    codigo = inspect.getsource(_reimputar_fifo)
    assert "item.es_ajuste" in codigo


def test_el_fifo_es_la_unica_puerta_de_consumo() -> None:
    # `egresar` no consume lotes: solo agrega el movimiento que la reimputación va
    # a ver. Un consumo hecho por fuera se restauraría solo y en silencio la
    # próxima vez que alguien editara o anulara una operación de divisas.
    assert "consumir_lotes_fifo" not in inspect.getsource(stock_usd.egresar)


def test_una_salida_sin_stock_suficiente_se_rechaza() -> None:
    # La primitiva es la misma que usan la venta y el ajuste que resta USD.
    with pytest.raises(ValidationError):
        consumir_lotes_fifo([(Decimal("1000"), Decimal("10"))], Decimal("50"))


# ── Deshacer: los dólares se van con su operación ─────────────────────

def test_no_se_puede_deshacer_lo_que_ya_se_vendio() -> None:
    # Quitar un lote consumido dejaría esas ventas sin el stock del que salieron y
    # reescribiría su ganancia ya reportada. Mismo criterio que anular un ajuste
    # en USD o un préstamo recibido en dólares.
    lote = stock_usd.ingresar(
        FakeDB(), monto=Decimal("300"), cotizacion=Decimal("1300"), fecha=None,
        origen_tipo="fiado_cobro", origen_id=None, detalle="x",
    )
    lote.usd_restante = Decimal("100.00")  # ya se vendieron 200
    with pytest.raises(ValidationError):
        stock_usd.borrar_por_origen(FakeDB([lote]), "fiado_cobro", None)


def test_un_lote_intacto_se_puede_deshacer() -> None:
    lote = stock_usd.ingresar(
        FakeDB(), monto=Decimal("300"), cotizacion=Decimal("1300"), fecha=None,
        origen_tipo="fiado_cobro", origen_id=None, detalle="x",
    )
    db = FakeDB([lote])
    stock_usd.borrar_por_origen(db, "fiado_cobro", None)
    assert db.borrados == [lote]


def test_una_salida_siempre_se_puede_deshacer() -> None:
    # Una salida no aporta stock a nadie: sacarla de la cadena solo devuelve los
    # dólares que había consumido.
    salida = stock_usd.egresar(
        FakeDB(), monto=Decimal("50"), fecha=None,
        origen_tipo="gasto", origen_id=None, detalle="x",
    )
    db = FakeDB([salida])
    stock_usd.borrar_por_origen(db, "gasto", None)
    assert db.borrados == [salida]


# ── El catálogo de la anulación tiene que estar completo ──────────────

def test_toda_entidad_que_mueve_stock_esta_en_el_catalogo() -> None:
    # Una entidad que mueva dólares y no esté acá deja sus movimientos vivos al
    # anularse: prestando su costo a una ganancia futura, o consumiendo un stock
    # que ya nadie sacó. No falla en ningún lado — solo descuadra.
    assert set(_ORIGENES_STOCK) == {
        "gasto", "deuda_simple", "prestamo", "fiado", "pasivo"
    }


def test_el_catalogo_de_stock_solo_nombra_entidades_anulables() -> None:
    # Un origen colgado de una entidad que el motor no conoce nunca se borraría.
    assert set(_ORIGENES_STOCK) <= set(_ENTIDADES)


def test_cada_lado_de_la_deuda_y_del_prestamo_tiene_su_origen() -> None:
    # El otorgamiento (salida) y los cobros (entrada) son movimientos distintos y
    # se distinguen por origen, igual que sus líneas de caja: rehacer el primero al
    # editar no debe tocar los segundos.
    assert _ORIGENES_STOCK["deuda_simple"] == ("deuda_simple", "deuda_simple_cobro")
    assert _ORIGENES_STOCK["prestamo"] == ("prestamo", "prestamo_cobro")


# ── El bot pide el costo, no lo inventa ───────────────────────────────

def test_el_prompt_exige_la_cotizacion_al_cobrar_en_dolares() -> None:
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert "cotizacion_stock" in _SYSTEM_PROMPT
    assert "TODO DÓLAR QUE ENTRA NECESITA SU COSTO" in _SYSTEM_PROMPT


def test_el_handler_del_bot_pregunta_en_vez_de_asumir() -> None:
    from app.services.whatsapp import dispatcher

    codigo = inspect.getsource(dispatcher._cobrar_deuda_cliente)
    assert "cotizacion_stock" in codigo
    assert "¿A cuánto tomás el dólar" in codigo
