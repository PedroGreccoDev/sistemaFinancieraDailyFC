from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    ChequeTipo,
    Cliente,
    Compensacion,
    MedioPago,
    Moneda,
    MovimientoCaja,
)
from app.services import reportes as service
from app.services.exceptions import ValidationError


class FakeDB:
    """Stand-in mínimo de Session: `scalars` devuelve los result-sets encolados.

    El servicio consulta `movimientos_caja`, después `cheques` y después
    `compensaciones`; este stub ignora el statement y va entregando las listas
    en ese orden. Una consulta para la que no se encoló nada devuelve vacío: el
    día que el feed sume otra fuente, los tests que no la miran no tienen por
    qué romperse.
    """

    def __init__(self, *result_sets: list) -> None:
        self._queue = list(result_sets)

    def scalars(self, _stmt):  # noqa: ANN001
        return iter(self._queue.pop(0) if self._queue else [])


def _caja(
    *,
    fecha: date,
    categoria: CajaCategoria,
    tipo: CajaTipo,
    monto: str,
    moneda: Moneda = Moneda.ARS,
    detalle: str | None = None,
    ganancia: str | None = None,
    # Toda línea del libro cae en una de las dos cajas: el medio es NOT NULL desde
    # la migración `0026` (§Caja paralela). El default refleja ese invariante.
    medio_pago: MedioPago = MedioPago.EFECTIVO,
    cotizacion: str | None = None,
    referencia_tipo: str | None = None,
) -> MovimientoCaja:
    return MovimientoCaja(
        id=uuid.uuid4(),
        fecha=fecha,
        moneda=moneda,
        tipo=tipo,
        categoria=categoria,
        monto=Decimal(monto),
        ganancia=None if ganancia is None else Decimal(ganancia),
        medio_pago=medio_pago,
        cotizacion=None if cotizacion is None else Decimal(cotizacion),
        referencia_tipo=referencia_tipo,
        referencia_id=uuid.uuid4() if referencia_tipo else None,
        detalle=detalle,
    )


def _cheque(*, created_at: datetime, estado: ChequeEstado = ChequeEstado.EN_CARTERA,
            cliente: Cliente | None = None, nro: str | None = "123", banco: str | None = None,
            monto: str = "100000") -> Cheque:
    c = Cheque(
        id=uuid.uuid4(),
        nro_cheque=nro,
        banco=banco,
        monto=Decimal(monto),
        porcentaje_compra=Decimal("0"),
        estado=estado,
    )
    c.created_at = created_at
    c.cliente_origen = cliente
    return c


DESDE = date(2026, 7, 1)
HASTA = date(2026, 7, 31)


def test_rango_invalido_lanza():
    with pytest.raises(ValidationError):
        service.get_movimientos_unificados(FakeDB([], []), HASTA, DESDE)


def test_incluye_lineas_de_caja_con_grupo_y_flujo():
    caja = [
        _caja(fecha=date(2026, 7, 10), categoria=CajaCategoria.COBRO_CUOTA,
              tipo=CajaTipo.INGRESO, monto="500.00", detalle="Cuota #1 - Ana"),
        _caja(fecha=date(2026, 7, 12), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="200.00", detalle="Nafta"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    assert len(items) == 2
    por_cat = {i.categoria: i for i in items}
    assert por_cat["COBRO_CUOTA"].grupo == "COBROS"
    assert por_cat["COBRO_CUOTA"].flujo == "INGRESO"
    assert por_cat["COBRO_CUOTA"].descripcion == "Cuota #1 - Ana"
    assert por_cat["GASTO"].grupo == "GASTOS"
    assert por_cat["GASTO"].flujo == "EGRESO"


def test_ingreso_de_cheque_es_neutro_y_en_grupo_cheques():
    cliente = Cliente(id=uuid.uuid4(), nombre="Pedro")
    cheques = [_cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                       cliente=cliente, nro="777", banco="Nación")]
    items = service.get_movimientos_unificados(FakeDB([], cheques), DESDE, HASTA)
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "INGRESO_CHEQUE"
    assert it.grupo == "CHEQUES"
    assert it.flujo == "NEUTRO"
    assert it.moneda == "ARS"
    assert it.referencia_tipo == "cheque"
    assert "777" in it.descripcion and "Pedro" in it.descripcion and "Nación" in it.descripcion


def test_cheque_fuera_de_rango_local_se_excluye():
    # 2026-08-01 02:00 UTC = 2026-07-31 23:00 ART -> entra (día 31).
    dentro = _cheque(created_at=datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc), nro="IN")
    # 2026-08-01 04:00 UTC = 2026-08-01 01:00 ART -> queda fuera del rango.
    fuera = _cheque(created_at=datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc), nro="OUT")
    items = service.get_movimientos_unificados(FakeDB([], [dentro, fuera]), DESDE, HASTA)
    nros = [i.descripcion for i in items]
    assert any("IN" in d for d in nros)
    assert not any("OUT" in d for d in nros)


def test_orden_por_fecha_descendente():
    caja = [
        _caja(fecha=date(2026, 7, 5), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="10.00"),
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="20.00"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    assert [i.fecha for i in items] == [date(2026, 7, 20), date(2026, 7, 5)]


def test_venta_usd_expone_ganancia_y_cotizacion():
    caja = [
        _caja(fecha=date(2026, 7, 8), categoria=CajaCategoria.VENTA_USD,
              tipo=CajaTipo.INGRESO, monto="150000.00", ganancia="5000.00",
              detalle="Venta de 100 USD @ $1500", referencia_tipo="movimiento"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    it = items[0]
    assert it.grupo == "DIVISAS"
    assert it.ganancia == Decimal("5000.00")
    assert it.referencia_tipo == "movimiento"


def test_un_echeq_sin_numero_no_se_muestra_como_None():
    """Se vio en pantalla: "Ingreso cheque Nº None de Paolini Hnos".

    El número puede faltar (§E-cheq) y esta línea lo interpolaba a mano, así que
    el `None` de Python llegaba tal cual a la pantalla de movimientos. El nombre
    lo arma `describir`, que es el único lugar que sabe qué hacer sin número.
    """
    cliente = Cliente(id=uuid.uuid4(), nombre="Paolini Hnos")
    sin_numero = _cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                         cliente=cliente, nro=None, banco=None, monto="1234567.00")
    sin_numero.tipo = ChequeTipo.ELECTRONICO
    items = service.get_movimientos_unificados(FakeDB([], [sin_numero]), DESDE, HASTA)
    assert "None" not in items[0].descripcion
    assert "e-cheq sin número ($1,234,567.00)" in items[0].descripcion
    assert "Paolini Hnos" in items[0].descripcion


def test_un_echeq_con_numero_se_nombra_como_echeq():
    """La misma pantalla llamaba "cheque" a un e-cheq: el operador no podía
    distinguir en la lista qué papel entró y cuál no existe."""
    con_numero = _cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                         nro="00001020", banco="Galicia")
    con_numero.tipo = ChequeTipo.ELECTRONICO
    items = service.get_movimientos_unificados(FakeDB([], [con_numero]), DESDE, HASTA)
    assert "e-cheq Nº 00001020 — Galicia" in items[0].descripcion


# ══════════════════════════════════════════════════════════════════════
#  Compensaciones: el evento sin efectivo que no se veía en ningún lado
# ══════════════════════════════════════════════════════════════════════

def _compensacion(
    *,
    fecha: date = date(2026, 7, 18),
    cliente: str = "Juan",
    acreedor: str = "Pedro",
    monto: str = "600000",
    moneda: Moneda = Moneda.ARS,
    moneda_deuda: Moneda = Moneda.ARS,
    moneda_pasivo: Moneda = Moneda.ARS,
    imputado_cliente: str | None = None,
    imputado_pasivo: str | None = None,
    excedente: str = "0",
    cotizacion: str | None = None,
) -> Compensacion:
    comp = Compensacion(
        id=uuid.uuid4(),
        fecha=fecha,
        cliente_id=uuid.uuid4(),
        acreedor=acreedor,
        moneda_pasivo=moneda_pasivo,
        moneda=moneda,
        monto=Decimal(monto),
        moneda_deuda=moneda_deuda,
        cotizacion=None if cotizacion is None else Decimal(cotizacion),
        imputado_cliente=Decimal(imputado_cliente if imputado_cliente is not None else monto),
        imputado_pasivo=Decimal(imputado_pasivo if imputado_pasivo is not None else monto),
        excedente=Decimal(excedente),
    )
    comp.cliente = Cliente(id=comp.cliente_id, nombre=cliente)
    return comp


def test_la_compensacion_aparece_como_evento_sin_efectivo():
    """Sin línea de caja, la operación no figuraba en ninguna pantalla del día.

    Bajan dos deudas y la caja no se mueve (§Compensación), así que el libro no
    la tiene; el operador igual necesita verla, y con los dos nombres: el
    registro de quién le transfirió a quién es todo lo que queda de ella.
    """
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "COMPENSACION"
    assert it.grupo == "COMPENSACIONES"
    assert it.flujo == "NEUTRO"
    assert it.monto == Decimal("600000.00")
    assert it.referencia_tipo == "compensacion"
    # Las dos puntas, en la dirección correcta: Juan le transfirió a Pedro.
    assert it.descripcion == "Compensación: Juan le transfirió a Pedro"


def test_la_compensacion_no_declara_medio_de_pago():
    # Ninguna de las dos cajas se movió: la plata fue de un tercero a otro.
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert items[0].medio_pago is None


def test_cross_moneda_muestra_cuanto_bajo_cada_lado():
    # Juan transfirió $600.000 contra una deuda suya en dólares: el monto de la
    # columna y lo que bajó la deuda son números distintos, y sin decirlo la
    # línea no se entiende.
    comp = _compensacion(
        moneda=Moneda.ARS,
        monto="600000",
        moneda_deuda=Moneda.USD,
        imputado_cliente="500",
        cotizacion="1200",
    )
    items = service.get_movimientos_unificados(FakeDB([], [], [comp]), DESDE, HASTA)
    it = items[0]
    assert "baja la deuda de Juan: U$D 500.00" in it.descripcion
    assert it.cotizacion == Decimal("1200")


def test_el_excedente_a_favor_se_nombra():
    # Transfirió más de lo que debía: la diferencia le quedó a favor y eso es
    # parte de lo que pasó ese día.
    comp = _compensacion(monto="700000", imputado_cliente="600000", excedente="100000")
    items = service.get_movimientos_unificados(FakeDB([], [], [comp]), DESDE, HASTA)
    descripcion = items[0].descripcion
    assert "baja la deuda de Juan: $600,000.00" in descripcion
    assert "a favor de Juan: $100,000.00" in descripcion


def test_compensacion_comun_no_repite_el_mismo_numero_tres_veces():
    # Misma moneda y sin excedente: el monto transferido, lo que bajó el cliente
    # y lo que bajó el acreedor son el mismo número, y la columna ya lo muestra.
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert "baja la deuda" not in items[0].descripcion


def test_las_compensaciones_se_ordenan_con_el_resto_del_dia():
    caja = [
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="10.00"),
    ]
    comp = [_compensacion(fecha=date(2026, 7, 25))]
    items = service.get_movimientos_unificados(FakeDB(caja, [], comp), DESDE, HASTA)
    assert [i.fecha for i in items] == [date(2026, 7, 25), date(2026, 7, 20)]
