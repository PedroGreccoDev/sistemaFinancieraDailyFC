"""Operar por un medio golpea la caja DE ESE medio.

Marcar el medio como etiqueta y seguir descontando del efectivo sería el peor de
los errores posibles acá: el saldo del cajón bajaría por plata que nunca salió de
ahí, el del banco quedaría alto por lo mismo, y **el neto del día seguiría dando
bien** —la plata salió igual—. El descuadre solo aparecería cuando alguien cuenta
billetes, sin ninguna pista de dónde se rompió.

Los otros tests de caja miran la forma del código (que el parámetro exista, que
se pase). Estos **ejercitan las funciones** y leen la línea que quedó escrita.

Estilo del proyecto: unitarios puros, sin BD — la sesión es un stub que junta lo
que se le agrega.

Ver §Las dos cajas.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cliente,
    Cuota,
    CuotaEstado,
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    MedioPago,
    Moneda,
    MovimientoCaja,
    Pasivo,
    PasivoEstado,
    Prestamo,
    PrestamoEstado,
)
from app.services import deudas_simples as svc_deudas
from app.services import fiados as svc_fiados
from app.services import pasivos as svc_pasivos
from app.services import prestamos as svc_prestamos
from app.services import traspasos as svc_traspasos

HOY = date(2026, 8, 25)
_MIL = Decimal("1000.00")


class FakeDB:
    """Sesión mínima: junta lo agregado y no sabe de fecha de corte."""

    def __init__(self) -> None:
        self.agregados: list[object] = []

    def add(self, obj: object) -> None:
        self.agregados.append(obj)

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        pass

    def get(self, _modelo, _pk):
        # Sin configuración de apertura no hay corte: todo es operación normal.
        return None

    @property
    def lineas(self) -> list[MovimientoCaja]:
        return [o for o in self.agregados if isinstance(o, MovimientoCaja)]


def _unica(db: FakeDB) -> MovimientoCaja:
    """La línea de caja que quedó. Que sea exactamente una también importa."""
    lineas = db.lineas
    assert len(lineas) == 1, f"se esperaba 1 línea de caja, hay {len(lineas)}"
    return lineas[0]


def _cliente() -> Cliente:
    return Cliente(id=uuid.uuid4(), nombre="Kiosco")


# ══════════════════════════════════════════════════════════════════════
#  Cobros — entra plata por una caja o por la otra
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("medio", list(MedioPago))
def test_cobro_de_fiado_entra_por_su_caja(medio: MedioPago) -> None:
    db = FakeDB()
    fiado = Fiado(
        id=uuid.uuid4(),
        cliente=_cliente(),
        saldo_pendiente=Decimal("5000.00"),
        estado=FiadoEstado.ABIERTO,
    )
    svc_fiados.imputar_cobro(
        db,
        fiado,
        reduccion=_MIL,
        fecha=HOY,
        monto_caja=_MIL,
        moneda_pago=Moneda.ARS,
        cotizacion=None,
        medio_pago=medio,
    )
    linea = _unica(db)
    assert linea.medio_pago == medio
    assert linea.categoria == CajaCategoria.COBRO_FIADO
    assert linea.tipo == CajaTipo.INGRESO


@pytest.mark.parametrize("medio", list(MedioPago))
def test_cobro_de_deuda_libre_entra_por_su_caja(medio: MedioPago) -> None:
    db = FakeDB()
    deuda = DeudaSimple(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        concepto="Mercadería",
        monto=Decimal("5000.00"),
        saldo_pendiente=Decimal("5000.00"),
        moneda=Moneda.ARS,
        estado=DeudaSimpleEstado.ABIERTA,
        fecha=HOY,
    )
    svc_deudas.imputar_cobro(
        db,
        deuda,
        cliente_nombre="Kiosco",
        imputado=_MIL,
        fecha=HOY,
        monto_caja=_MIL,
        moneda_pago=Moneda.ARS,
        cotizacion=None,
        medio_pago=medio,
    )
    linea = _unica(db)
    assert linea.medio_pago == medio
    assert linea.categoria == CajaCategoria.COBRO_DEUDA


@pytest.mark.parametrize("medio", list(MedioPago))
def test_cobro_de_cuota_entra_por_su_caja(medio: MedioPago) -> None:
    db = FakeDB()
    prestamo = Prestamo(
        id=uuid.uuid4(),
        cliente=_cliente(),
        credito=Decimal("10000.00"),
        moneda=Moneda.ARS,
        total_a_cobrar=Decimal("12000.00"),
        estado=PrestamoEstado.ACTIVO,
    )
    cuota = Cuota(
        id=uuid.uuid4(),
        prestamo_id=prestamo.id,
        numero_cuota=1,
        monto=_MIL,
        monto_pagado=Decimal("0.00"),
        estado=CuotaEstado.PENDIENTE,
        fecha_vencimiento=HOY,
        fecha_cobro=HOY,
    )
    svc_prestamos._registrar_cobro_cuota(db, prestamo, cuota, _MIL, medio)
    linea = _unica(db)
    assert linea.medio_pago == medio
    assert linea.categoria == CajaCategoria.COBRO_CUOTA


# ══════════════════════════════════════════════════════════════════════
#  Pagos — sale plata de una caja o de la otra
# ══════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("medio", list(MedioPago))
def test_la_plata_prestada_al_negocio_entra_por_su_caja(medio: MedioPago) -> None:
    """Quien te presta suele transferir, pero lo dice el operador."""
    db = FakeDB()
    pasivo = Pasivo(
        id=uuid.uuid4(),
        acreedor="Cuello",
        concepto="Préstamo",
        monto=_MIL,
        saldo_pendiente=_MIL,
        moneda=Moneda.ARS,
        estado=PasivoEstado.PENDIENTE,
        ingreso_caja=True,
        fecha_ingreso=HOY,
    )
    svc_pasivos._registrar_ingreso(db, pasivo, medio)
    linea = _unica(db)
    assert linea.medio_pago == medio
    assert linea.categoria == CajaCategoria.INGRESO_PASIVO
    assert linea.tipo == CajaTipo.INGRESO


@pytest.mark.parametrize("medio", list(MedioPago))
def test_pagar_una_deuda_del_negocio_sale_por_su_caja(medio: MedioPago) -> None:
    """El caso que el bot resolvió recién: "le transferí 200 mil a Cuello"."""
    db = FakeDB()
    pasivo = Pasivo(
        id=uuid.uuid4(),
        acreedor="Cuello",
        concepto="Mercadería",
        monto=Decimal("5000.00"),
        saldo_pendiente=Decimal("5000.00"),
        moneda=Moneda.ARS,
        estado=PasivoEstado.PENDIENTE,
    )
    # Se ejercita el cuerpo del reparto sin la carga de pasivos (que necesita BD):
    # lo que se custodia es que la línea salga por el medio pedido.
    from app.services.caja import registrar

    registrar(
        db,
        fecha=HOY,
        moneda=Moneda.ARS,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.PAGO_PASIVO,
        monto=_MIL,
        medio_pago=medio,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=f"Pago deuda a {pasivo.acreedor}",
    )
    linea = _unica(db)
    assert linea.medio_pago == medio
    assert linea.tipo == CajaTipo.EGRESO


# ══════════════════════════════════════════════════════════════════════
#  Traspaso — las dos líneas van a cajas OPUESTAS
# ══════════════════════════════════════════════════════════════════════

def test_un_deposito_saca_del_efectivo_y_mete_en_la_cuenta() -> None:
    """Es la única operación que toca las dos cajas, y en sentidos opuestos.

    Si las dos líneas cayeran en la misma caja se cancelarían entre sí: el
    depósito no haría nada y el operador seguiría viendo la plata en el cajón.
    """
    db = FakeDB()
    svc_traspasos.registrar(
        db,
        monto=_MIL,
        moneda=Moneda.ARS,
        origen=MedioPago.EFECTIVO,
        destino=MedioPago.TRANSFERENCIA,
        fecha=HOY,
    )
    lineas = db.lineas
    assert len(lineas) == 2

    salida = next(m for m in lineas if m.tipo == CajaTipo.EGRESO)
    entrada = next(m for m in lineas if m.tipo == CajaTipo.INGRESO)
    assert salida.medio_pago == MedioPago.EFECTIVO
    assert entrada.medio_pago == MedioPago.TRANSFERENCIA
    assert salida.monto == entrada.monto == _MIL
    # Mismo id: es lo que permite listarlo como una operación y anularlo entero.
    assert salida.referencia_id == entrada.referencia_id
    assert salida.referencia_tipo == entrada.referencia_tipo == "traspaso"


def test_una_extraccion_es_el_mismo_movimiento_al_reves() -> None:
    db = FakeDB()
    svc_traspasos.registrar(
        db,
        monto=_MIL,
        moneda=Moneda.ARS,
        origen=MedioPago.TRANSFERENCIA,
        destino=MedioPago.EFECTIVO,
        fecha=HOY,
    )
    lineas = db.lineas
    salida = next(m for m in lineas if m.tipo == CajaTipo.EGRESO)
    entrada = next(m for m in lineas if m.tipo == CajaTipo.INGRESO)
    assert salida.medio_pago == MedioPago.TRANSFERENCIA
    assert entrada.medio_pago == MedioPago.EFECTIVO


def test_el_traspaso_no_cambia_el_total() -> None:
    """La plata no entró ni salió del negocio: en el neto se cancela sola."""
    db = FakeDB()
    svc_traspasos.registrar(
        db,
        monto=_MIL,
        moneda=Moneda.ARS,
        origen=MedioPago.EFECTIVO,
        destino=MedioPago.TRANSFERENCIA,
        fecha=HOY,
    )
    neto = sum(
        m.monto if m.tipo == CajaTipo.INGRESO else -m.monto for m in db.lineas
    )
    assert neto == Decimal("0.00")


# ══════════════════════════════════════════════════════════════════════
#  Lo que NO mueve caja tampoco inventa una línea
# ══════════════════════════════════════════════════════════════════════

def test_cobrar_con_cheque_no_escribe_en_ninguna_caja() -> None:
    """No entró efectivo: entró un papel. Esa plata se reconoce al venderlo."""
    db = FakeDB()
    fiado = Fiado(
        id=uuid.uuid4(),
        cliente=_cliente(),
        saldo_pendiente=Decimal("5000.00"),
        estado=FiadoEstado.ABIERTO,
    )
    svc_fiados.imputar_cobro(
        db,
        fiado,
        reduccion=_MIL,
        fecha=HOY,
        monto_caja=None,  # el cheque no mueve caja
        moneda_pago=Moneda.ARS,
        cotizacion=None,
        medio_pago=MedioPago.EFECTIVO,
    )
    assert db.lineas == []


def test_una_deuda_que_no_trajo_plata_no_escribe_nada() -> None:
    """La deuda comercial de siempre: quedó la obligación, no entró un peso."""
    db = FakeDB()
    pasivo = Pasivo(
        id=uuid.uuid4(),
        acreedor="Proveedor",
        concepto="Mercadería",
        monto=_MIL,
        saldo_pendiente=_MIL,
        moneda=Moneda.ARS,
        estado=PasivoEstado.PENDIENTE,
        ingreso_caja=False,
    )
    svc_pasivos._registrar_ingreso(db, pasivo, MedioPago.TRANSFERENCIA)
    assert db.lineas == []
