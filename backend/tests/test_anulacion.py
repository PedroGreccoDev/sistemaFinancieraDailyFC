"""Reglas de bloqueo del motor de anulación (§ régimen 2026-08-06).

Estilo del proyecto: unitarios puros, sin BD. Se arman instancias de modelo en
memoria y, donde el validador necesita una sesión, se usa un stub mínimo.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from app.db.models import (
    Cheque,
    ChequeEstado,
    Fiado,
    FiadoEstado,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.services.anulacion import (
    _ENTIDADES,
    _deuda_inicial_fiado,
    _validar_cheque,
    _validar_fiado,
    _validar_movimiento,
)


class FakeDB:
    """Sesión mínima: devuelve lo que se le programe en `resultado`."""

    def __init__(self, resultado: object = None) -> None:
        self.resultado = resultado

    def scalar(self, *_args, **_kwargs) -> object:
        return self.resultado


def _fiado(monto: str, porcentaje: str, saldo: str) -> Fiado:
    return Fiado(
        id=uuid.uuid4(),
        cheque_id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        monto_original=Decimal(monto),
        porcentaje_venta=Decimal(porcentaje),
        saldo_pendiente=Decimal(saldo),
        estado=FiadoEstado.ABIERTO,
    )


def _cheque(estado: ChequeEstado = ChequeEstado.EN_CARTERA) -> Cheque:
    return Cheque(
        id=uuid.uuid4(),
        nro_cheque="00012345",
        banco="Galicia",
        monto=Decimal("100000.00"),
        porcentaje_compra=Decimal("10"),
        estado=estado,
    )


def _movimiento(tipo: MovimientoEfectivoTipo, monto: str, restante: str) -> MovimientoEfectivo:
    # fecha_operacion/created_at vienen siempre de la BD en el flujo real; acá se
    # fijan a mano porque el validador los usa para ordenar la cadena FIFO.
    momento = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    return MovimientoEfectivo(
        id=uuid.uuid4(),
        tipo=tipo,
        monto=Decimal(monto),
        usd_restante=Decimal(restante),
        cotizacion_aplicada=Decimal("1000"),
        fecha_operacion=momento,
        created_at=momento,
    )


# ── Fiados ────────────────────────────────────────────────────────────

def test_deuda_inicial_fiado_descuenta_el_porcentaje() -> None:
    # 100.000 al 10% de descuento → el cliente debe 90.000.
    assert _deuda_inicial_fiado(_fiado("100000", "10", "90000")) == Decimal("90000.00")


def test_fiado_sin_cobros_se_puede_anular() -> None:
    bloqueo, _ = _validar_fiado(_fiado("100000", "10", "90000"))
    assert bloqueo is None


def test_fiado_con_cobro_parcial_bloquea() -> None:
    # Deuda inicial 90.000, ya pagó 15.000: anularlo dejaría esos 15.000 huérfanos.
    bloqueo, _ = _validar_fiado(_fiado("100000", "10", "75000"))
    assert bloqueo is not None
    assert "15,000.00" in bloqueo


def test_fiado_totalmente_cobrado_bloquea() -> None:
    bloqueo, _ = _validar_fiado(_fiado("100000", "10", "0"))
    assert bloqueo is not None


# ── Cheques ───────────────────────────────────────────────────────────

def test_cheque_simple_se_puede_anular() -> None:
    bloqueo, arrastra = _validar_cheque(FakeDB(), _cheque())
    assert bloqueo is None
    assert arrastra == []


def test_cheque_fiado_sin_cobros_arrastra_el_fiado() -> None:
    cheque = _cheque(ChequeEstado.FIADO)
    cheque.fiado_originado = _fiado("100000", "10", "90000")
    bloqueo, arrastra = _validar_cheque(FakeDB(), cheque)
    assert bloqueo is None
    assert len(arrastra) == 1
    assert "fiado" in arrastra[0]


def test_cheque_fiado_con_cobros_bloquea() -> None:
    cheque = _cheque(ChequeEstado.FIADO)
    cheque.fiado_originado = _fiado("100000", "10", "50000")
    bloqueo, arrastra = _validar_cheque(FakeDB(), cheque)
    assert bloqueo is not None
    assert "cobros parciales" in bloqueo
    assert arrastra == []


def test_cheque_usado_para_pagar_pasivo_bloquea() -> None:
    # El FakeDB devuelve una línea de caja PAGO_PASIVO para este cheque.
    bloqueo, _ = _validar_cheque(FakeDB(resultado=object()), _cheque())
    assert bloqueo is not None
    assert "deuda del negocio" in bloqueo


# ── Divisas (FIFO) ────────────────────────────────────────────────────

def test_compra_con_lote_intacto_se_puede_anular() -> None:
    bloqueo, _ = _validar_movimiento(
        FakeDB(), _movimiento(MovimientoEfectivoTipo.COMPRA, "1000", "1000")
    )
    assert bloqueo is None


def test_compra_con_lote_consumido_bloquea() -> None:
    # De 1000 USD comprados ya se vendieron 400: anularla reescribiría la ganancia
    # de esa venta, que ya se reportó.
    bloqueo, _ = _validar_movimiento(
        FakeDB(), _movimiento(MovimientoEfectivoTipo.COMPRA, "1000", "600")
    )
    assert bloqueo is not None
    assert "400" in bloqueo


def test_ultima_venta_se_puede_anular() -> None:
    bloqueo, _ = _validar_movimiento(
        FakeDB(), _movimiento(MovimientoEfectivoTipo.VENTA, "500", "0")
    )
    assert bloqueo is None


def test_venta_con_posteriores_bloquea() -> None:
    # FakeDB devuelve una venta posterior → esta no es la última.
    bloqueo, _ = _validar_movimiento(
        FakeDB(resultado=object()), _movimiento(MovimientoEfectivoTipo.VENTA, "500", "0")
    )
    assert bloqueo is not None
    assert "última venta" in bloqueo


# ── Catálogo de entidades ─────────────────────────────────────────────

def test_toda_entidad_anulable_declara_sus_referencias_de_caja() -> None:
    """Si una entidad quedara sin sus `referencia_tipo`, la anulación la marcaría
    como dada de baja pero dejaría sus líneas de caja vivas: la plata seguiría
    contando en el reporte. Este test fija el mapa completo."""
    esperado = {
        "cheque": ("cheque",),
        "prestamo": ("prestamo", "cuota"),
        "movimiento_efectivo": ("movimiento_efectivo",),
        "fiado": ("fiado",),
        "deuda_simple": ("deuda_simple", "deuda_simple_cobro"),
        "pasivo": ("pasivo",),
        "gasto": ("gasto",),
    }
    assert {k: v.refs for k, v in _ENTIDADES.items()} == esperado


def test_las_referencias_coinciden_con_las_que_escriben_los_servicios() -> None:
    """Las constantes de referencia viven en cada servicio; si alguna cambiara,
    la anulación dejaría de encontrar sus líneas y la caja quedaría descuadrada."""
    from app.services.deudas_simples import _REF_COBRO, _REF_ORIGEN
    from app.services.movimientos import _REF as REF_DIVISAS

    assert _REF_ORIGEN in _ENTIDADES["deuda_simple"].refs
    assert _REF_COBRO in _ENTIDADES["deuda_simple"].refs
    assert REF_DIVISAS in _ENTIDADES["movimiento_efectivo"].refs


# ── Intent del bot ────────────────────────────────────────────────────

def test_revertir_operacion_es_un_intent_valido() -> None:
    """Si el intent no está en la lista blanca, el parser lo descarta a
    DESCONOCIDO y el bot responde "no entendí" en vez de revertir."""
    from app.services.ia.claude import INTENTS

    assert "REVERTIR_OPERACION" in INTENTS


def test_el_prompt_distingue_revertir_de_editar() -> None:
    """Editar corrige un valor mal cargado; revertir deshace la operación. Si el
    prompt no marcara la diferencia, un "no se vendió" terminaría editando el
    porcentaje en vez de devolver el cheque a cartera."""
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert "REVERTIR_OPERACION" in _SYSTEM_PROMPT
    assert "NO confundir con EDITAR_OPERACION" in _SYSTEM_PROMPT
    # La reversión es destructiva: el prompt debe exigir confirmación.
    seccion = _SYSTEM_PROMPT.split("15. REVERTIR_OPERACION")[1].split("16.")[0]
    assert "confirmacion_requerida: true" in seccion


def test_el_dispatcher_registra_el_intent() -> None:
    """El intent tiene que estar cableado al handler, no solo documentado."""
    import inspect

    from app.services.whatsapp import dispatcher

    fuente = inspect.getsource(dispatcher.dispatch)
    assert 'intent == "REVERTIR_OPERACION"' in fuente
    assert hasattr(dispatcher, "_revertir_operacion")


def test_el_handler_de_reversion_no_usa_nombres_sin_importar() -> None:
    """Los nombres que el handler usa solo dentro de la función no se validan al
    importar el módulo: un modelo sin importar explota recién cuando el operador
    pide esa reversión por WhatsApp. Este test los compila contra el módulo."""
    import inspect

    from app.services.whatsapp import dispatcher

    fuente = inspect.getsource(dispatcher._resolver_para_anular)
    for nombre in ("MovimientoEfectivo", "Pasivo", "Prestamo", "select"):
        assert nombre in fuente, f"el test quedó desactualizado: {nombre} ya no se usa"
        assert hasattr(dispatcher, nombre), f"{nombre} se usa pero no está importado"
