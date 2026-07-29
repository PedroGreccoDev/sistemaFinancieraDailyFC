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
    Cliente,
    MedioPago,
    Moneda,
    MovimientoCaja,
)
from app.services import reportes as service
from app.services.exceptions import ValidationError


class FakeDB:
    """Stand-in mínimo de Session: `scalars` devuelve los result-sets encolados.

    El servicio consulta primero `movimientos_caja` y luego `cheques`; este stub
    ignora el statement y va entregando las listas en ese orden.
    """

    def __init__(self, *result_sets: list) -> None:
        self._queue = list(result_sets)

    def scalars(self, _stmt):  # noqa: ANN001
        return iter(self._queue.pop(0))


def _caja(
    *,
    fecha: date,
    categoria: CajaCategoria,
    tipo: CajaTipo,
    monto: str,
    moneda: Moneda = Moneda.ARS,
    detalle: str | None = None,
    ganancia: str | None = None,
    medio_pago: MedioPago | None = None,
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
            cliente: Cliente | None = None, nro: str = "123", banco: str | None = None,
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
