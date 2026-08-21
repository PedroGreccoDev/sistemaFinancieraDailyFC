"""La deuda que SÍ hace entrar plata: alguien le presta al negocio (§5).

Una deuda del negocio normalmente no mueve la caja —le debo al proveedor por la
mercadería y no entró un peso—. Pero cuando le **prestan** plata, la deuda nace y
además el efectivo entra al cajón: sin asentar ese ingreso el reporte del día
queda corto contra la plata real, y el descuadre es por el monto entero.

Estos tests custodian las dos mitades del asunto: que el prompt siga separando los
dos casos (es la parte que puede leerse mal) y que el asiento se haga —y se
rehaga— sin llevarse puestos los pagos del mismo pasivo. Unitarios puros: no
llaman al modelo ni tocan la BD.
"""

from __future__ import annotations

import inspect
import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
    Pasivo,
    PasivoEstado,
)
from app.services import anulacion as svc_anulacion
from app.services import caja as svc_caja
from app.services import pasivos as svc_pasivos
from app.services import reportes as svc_reportes
from app.services.exceptions import ConflictError, ValidationError
from app.services.ia.claude import _SYSTEM_PROMPT
from app.services.whatsapp import dispatcher


# ── Dobles mínimos ───────────────────────────────────────────────────────────

class FakeDB:
    """Sesión mínima: solo junta lo que se le agrega."""

    def __init__(self) -> None:
        self.agregados: list[object] = []

    def add(self, obj: object) -> None:
        self.agregados.append(obj)


class FakeQuery:
    """Query encadenable que cuenta los filtros y si se llamó a `delete`."""

    def __init__(self) -> None:
        self.filtros = 0
        self.borrado = False

    def filter(self, *args) -> "FakeQuery":
        self.filtros += len(args)
        return self

    def delete(self, **_kwargs) -> None:
        self.borrado = True


class FakeDBConQuery(FakeDB):
    def __init__(self) -> None:
        super().__init__()
        self.q = FakeQuery()

    def query(self, *_args, **_kwargs) -> FakeQuery:
        return self.q


class FakeDBConId(FakeDB):
    """`flush` le pone id a lo agregado, como haría la BD al insertar."""

    def flush(self) -> None:
        for obj in self.agregados:
            if getattr(obj, "id", None) is None:
                obj.id = uuid.uuid4()


class FakeDBConGet(FakeDB):
    """Devuelve el lote programado y anota qué se borró."""

    def __init__(self, lote: object) -> None:
        super().__init__()
        self.lote = lote
        self.borrados: list[object] = []

    def get(self, *_args, **_kwargs) -> object:
        return self.lote

    def delete(self, obj: object) -> None:
        self.borrados.append(obj)


def _pasivo(*, ingreso_caja: bool, moneda: Moneda = Moneda.ARS) -> Pasivo:
    return Pasivo(
        id=uuid.uuid4(),
        acreedor="Fernando",
        concepto="Me prestó plata",
        monto=Decimal("500000.00"),
        saldo_pendiente=Decimal("500000.00"),
        moneda=moneda,
        estado=PasivoEstado.PENDIENTE,
        ingreso_caja=ingreso_caja,
        fecha_ingreso=date(2026, 8, 21) if ingreso_caja else None,
    )


# ── El asiento ───────────────────────────────────────────────────────────────

def test_la_deuda_comun_no_mueve_la_caja() -> None:
    """El caso normal y el que tiene que seguir siendo el default: se anota la
    obligación y no entra un peso."""
    db = FakeDB()
    svc_pasivos._registrar_ingreso(db, _pasivo(ingreso_caja=False))
    assert db.agregados == []


def test_el_prestamo_recibido_asienta_el_ingreso() -> None:
    """Entró la plata: una línea INGRESO por el monto, en la moneda de la deuda
    y en el día en que la recibieron."""
    db = FakeDB()
    pasivo = _pasivo(ingreso_caja=True, moneda=Moneda.USD)
    svc_pasivos._registrar_ingreso(db, pasivo)

    assert len(db.agregados) == 1
    mov = db.agregados[0]
    assert mov.tipo == CajaTipo.INGRESO
    assert mov.categoria == CajaCategoria.INGRESO_PASIVO
    assert mov.monto == Decimal("500000.00")
    assert mov.moneda == Moneda.USD
    assert mov.fecha == date(2026, 8, 21)
    # La referencia es la que usa el motor de anulación para revertirlo.
    assert (mov.referencia_tipo, mov.referencia_id) == ("pasivo", pasivo.id)


def test_el_resync_no_se_lleva_puestos_los_pagos() -> None:
    """Un pasivo lleva su INGRESO_PASIVO y un PAGO_PASIVO por cada pago, todos
    bajo la misma referencia. Rehacer el primero sin acotar por categoría
    borraría los pagos: plata que salió de verdad, desaparecida del reporte."""
    fuente = inspect.getsource(svc_pasivos._resync_caja_ingreso)
    assert "categoria=CajaCategoria.INGRESO_PASIVO" in fuente


def test_borrar_por_referencia_acota_cuando_le_dan_categoria() -> None:
    """La contraparte del test anterior, del lado del helper: con categoría
    filtra por una condición más que sin ella."""
    sin_cat = FakeDBConQuery()
    svc_caja.borrar_por_referencia(sin_cat, "pasivo", uuid.uuid4())

    con_cat = FakeDBConQuery()
    svc_caja.borrar_por_referencia(
        con_cat, "pasivo", uuid.uuid4(), categoria=CajaCategoria.INGRESO_PASIVO
    )

    assert sin_cat.q.borrado and con_cat.q.borrado
    assert con_cat.q.filtros == sin_cat.q.filtros + 1


def test_editar_rehace_la_linea_si_cambia_algo_de_ella() -> None:
    """Monto, moneda y fecha SON la línea de caja; acreedor y concepto, su
    detalle. Si la edición no la rehiciera, la caja quedaría con el valor viejo."""
    for campo in ("ingreso_caja", "fecha_ingreso", "monto", "moneda", "acreedor", "concepto"):
        assert campo in svc_pasivos._CAMPOS_INGRESO


def test_la_categoria_entra_en_el_reporte() -> None:
    """Una categoría sin grupo ni etiqueta sale del reporte como una línea
    huérfana, sin nombre y fuera de los filtros del panel."""
    assert svc_reportes._GRUPO_POR_CATEGORIA[CajaCategoria.INGRESO_PASIVO] == "PASIVOS"
    assert CajaCategoria.INGRESO_PASIVO in svc_reportes._LABEL_CATEGORIA


# ── El bot ───────────────────────────────────────────────────────────────────

def _seccion_registrar_deuda() -> str:
    return _SYSTEM_PROMPT.split("10. REGISTRAR_DEUDA  ←")[1].split(
        "10b. REGISTRAR_DEUDA_CLIENTE"
    )[0]


def test_el_prompt_separa_la_deuda_que_trae_plata_de_la_que_no() -> None:
    """Las dos se dicen "le debo a X" y mueven la caja distinto. El prompt tiene
    que contrastarlas con las frases que el operador usa de verdad."""
    seccion = _seccion_registrar_deuda()
    assert "ingreso_caja" in seccion
    assert "me prestó" in seccion
    assert "LA PLATA LLEGÓ A TUS MANOS" in seccion


def test_el_prompt_contrasta_me_presto_con_le_preste() -> None:
    """Un pronombre de diferencia y se invierten las dos cosas a la vez: el
    sentido de la caja y quién le debe a quién."""
    seccion = _seccion_registrar_deuda()
    assert '"ME PRESTÓ" vs "LE PRESTÉ"' in seccion
    assert "NUEVO_PRESTAMO" in seccion
    assert "REGISTRAR_DEUDA_CLIENTE" in seccion


def test_ante_la_duda_no_inventa_el_ingreso() -> None:
    """Marcar de más mete en la caja plata que nunca entró. El default es el
    caso normal, y el operador lo corrige leyendo la respuesta."""
    seccion = _seccion_registrar_deuda()
    assert "ingreso_caja: false (el caso normal)" in seccion


def test_el_handler_pasa_la_marca_al_servicio() -> None:
    """Sin esto el bot entiende bien el mensaje y igual no asienta el ingreso."""
    fuente = inspect.getsource(dispatcher._registrar_deuda)
    assert 'data.get("ingreso_caja")' in fuente
    assert "ingreso_caja=ingreso_caja" in fuente


def test_la_respuesta_dice_para_donde_fue_la_caja() -> None:
    """Es el control inmediato del operador: si le contesta "no mueve la caja" y
    la plata sí entró, lo corrige en el momento."""
    fuente = inspect.getsource(dispatcher._registrar_deuda)
    assert "Entró a caja el" in fuente
    assert "No mueve la caja" in fuente


def test_se_puede_corregir_desde_el_chat() -> None:
    """El error más caro de esta operación —la caja corta o larga por el monto
    entero— tiene que poder arreglarse sin entrar al panel."""
    fuente = inspect.getsource(dispatcher._editar_pasivo)
    assert '"ingreso_caja"' in fuente
    # Y la edición va por el servicio, que es quien rehace la línea de caja y
    # recalcula el saldo; escribiendo los campos a mano quedaban desfasados.
    assert "svc_pasivos.editar_pasivo" in fuente


@pytest.mark.parametrize("val,esperado", [("si", True), ("sí", True), ("no", False), (True, True)])
def test_el_si_o_no_del_operador(val: object, esperado: bool) -> None:
    assert dispatcher._parse_bool_val(val) is esperado


def test_lo_que_no_se_entiende_se_rechaza() -> None:
    """Caer en `False` por default borraría un ingreso de caja que sí existió."""
    with pytest.raises(ValueError):
        dispatcher._parse_bool_val("mas o menos")


# ── Dólares prestados: la caja no alcanza, hace falta el stock ───────────────

def test_los_dolares_prestados_exigen_su_cotizacion() -> None:
    """La caja USD y lo que se puede vender son cosas distintas: la venta consume
    lotes con su costo. Sin cotización no hay lote, y el error aparecería recién
    el día que quiera venderlos —cuando ya nadie se acuerda a cuánto estaba—."""
    with pytest.raises(ValidationError):
        svc_pasivos._exigir_cotizacion_usd(Moneda.USD, None)
    with pytest.raises(ValidationError):
        svc_pasivos._exigir_cotizacion_usd(Moneda.USD, Decimal("0"))


def test_en_pesos_no_se_pide_ninguna_cotizacion() -> None:
    """Los pesos no tienen stock que alimentar: pedir una cotización sería
    fricción pura en la carga que más se usa."""
    svc_pasivos._exigir_cotizacion_usd(Moneda.ARS, None)  # no levanta


def test_el_lote_entra_al_costo_declarado_y_sin_tocar_la_caja() -> None:
    """El lote se inserta directo, no como compra: la caja USD ya la mueve el
    INGRESO_PASIVO, y una compra además restaría pesos que nunca salieron."""
    db = FakeDBConId()
    pasivo = _pasivo(ingreso_caja=True, moneda=Moneda.USD)
    pasivo.cotizacion_ingreso_usd = Decimal("1250.00")

    lote = svc_pasivos._crear_lote_usd(db, pasivo)

    assert lote is not None
    assert lote.tipo == MovimientoEfectivoTipo.COMPRA
    assert lote.monto == lote.usd_restante == pasivo.monto  # intacto
    assert lote.cotizacion_aplicada == Decimal("1250.00")
    assert lote.ganancia == Decimal("0.00")
    # `es_ajuste` es la marca de "stock que entró sin una compra detrás": la
    # comparte con la apertura y los ajustes, y es lo que evita que se le asiente
    # caja al editarlo o que figure como una compra que nunca ocurrió.
    assert lote.es_ajuste is True
    assert pasivo.lote_id == lote.id


def test_un_prestamo_en_pesos_no_crea_lote() -> None:
    db = FakeDBConId()
    assert svc_pasivos._crear_lote_usd(db, _pasivo(ingreso_caja=True, moneda=Moneda.ARS)) is None


def test_no_se_toca_la_deuda_si_esos_dolares_ya_se_vendieron() -> None:
    """Sacar el lote dejaría esas ventas sin el stock del que salieron y
    reescribiría su ganancia ya reportada. Mismo criterio que los ajustes en USD."""
    pasivo = _pasivo(ingreso_caja=True, moneda=Moneda.USD)
    lote = MovimientoEfectivo(
        id=uuid.uuid4(), tipo=MovimientoEfectivoTipo.COMPRA, moneda=Moneda.USD,
        monto=Decimal("1000.00"), cotizacion_aplicada=Decimal("1250.00"),
        ganancia=Decimal("0.00"), usd_restante=Decimal("400.00"),  # se vendieron 600
    )
    pasivo.lote_id = lote.id

    db = FakeDBConGet(lote)
    with pytest.raises(ConflictError):
        svc_pasivos._borrar_lote_usd(db, pasivo)

    # Y la anulación se frena por el mismo motivo, con su aviso al operador.
    bloqueo, _ = svc_anulacion._validar_pasivo(FakeDBConGet(lote), pasivo)
    assert bloqueo is not None and "ya fueron vendidos" in bloqueo


def test_el_lote_intacto_se_puede_sacar() -> None:
    """Si nadie vendió nada, corregir o anular la deuda se lleva su stock: esos
    dólares no entraron nunca."""
    pasivo = _pasivo(ingreso_caja=True, moneda=Moneda.USD)
    lote = MovimientoEfectivo(
        id=uuid.uuid4(), tipo=MovimientoEfectivoTipo.COMPRA, moneda=Moneda.USD,
        monto=Decimal("1000.00"), cotizacion_aplicada=Decimal("1250.00"),
        ganancia=Decimal("0.00"), usd_restante=Decimal("1000.00"),
    )
    pasivo.lote_id = lote.id

    assert svc_anulacion._validar_pasivo(FakeDBConGet(lote), pasivo)[0] is None

    db = FakeDBConGet(lote)
    svc_pasivos._borrar_lote_usd(db, pasivo)
    assert db.borrados == [lote]
    assert pasivo.lote_id is None


def test_una_deuda_sin_stock_se_anula_siempre() -> None:
    """La deuda comercial de siempre no tiene lote: nada que validar."""
    assert svc_anulacion._validar_pasivo(FakeDBConGet(None), _pasivo(ingreso_caja=False)) == (None, [])


def test_el_prompt_pide_la_cotizacion_de_los_dolares() -> None:
    """"Me prestó 1.000 dólares" sin cotización no se puede cargar, y el bot es
    el único que puede pedirla a tiempo — después nadie se acuerda."""
    seccion = _seccion_registrar_deuda()
    assert "cotizacion_ingreso_usd" in seccion
    assert "DÓLARES PRESTADOS: PEDÍ LA COTIZACIÓN" in seccion
    assert "ACLARACION_REQUERIDA" in seccion
