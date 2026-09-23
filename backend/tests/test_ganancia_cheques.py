"""Lo que deja el negocio de cheques, en el reporte de cierre (§7).

El dato contesta "¿cuánto gané comprando y vendiendo papel en estos días?", y la
regla es una sola: **la ganancia se fija el día que el cheque sale de la
cartera**. Lo que cambia según por dónde salió es la cuenta, y eso es lo que se
prueba acá (la suma por período la hace la consulta; ahí no hay nada que probar).
"""
from __future__ import annotations

import uuid
from decimal import Decimal

from app.db.models import Cheque, ChequeEstado
from app.services.cheques import ganancia_realizada, neto_compra


def _cheque(
    estado: ChequeEstado,
    *,
    monto: str = "1000000",
    compra: str = "10",
    venta: str | None = None,
    ganancia: str = "0.00",
) -> Cheque:
    return Cheque(
        id=uuid.uuid4(),
        nro_cheque="12345",
        banco="Galicia",
        monto=Decimal(monto),
        porcentaje_compra=Decimal(compra),
        porcentaje_venta=Decimal(venta) if venta is not None else None,
        ganancia=Decimal(ganancia),
        estado=estado,
    )


def test_el_cheque_en_cartera_todavia_no_gano_nada() -> None:
    """Comprarlo no es ganancia: el papel podría venderse, cobrarse o rebotar."""
    assert ganancia_realizada(_cheque(ChequeEstado.EN_CARTERA)) == Decimal("0.00")


def test_vendido_reconoce_lo_que_reconocio_la_venta() -> None:
    """Sale de `cheque.ganancia` —el número que escribió la venta y que muestra
    la cartera—, no de recalcular la fórmula: dos cuentas para el mismo peso son
    dos números distintos el día que una cambie."""
    c = _cheque(ChequeEstado.VENDIDO, compra="10", venta="6", ganancia="40000.00")
    assert ganancia_realizada(c) == Decimal("40000.00")


def test_cobrado_gana_TODO_el_descuento_de_compra() -> None:
    """Al vencimiento entra el nominal completo: lo ganado es el descuento entero
    con el que se compró, no una diferencia contra otro porcentaje."""
    c = _cheque(ChequeEstado.COBRADO, monto="1000000", compra="10")
    assert ganancia_realizada(c) == Decimal("100000.00")


def test_cobrado_no_se_queda_con_la_ganancia_de_venta() -> None:
    """`ganancia` solo la escribe la venta, así que un cobrado la tiene en cero:
    leerla en vez de calcular dejaría todos los cobros sin ganancia."""
    c = _cheque(ChequeEstado.COBRADO, monto="500000", compra="8", ganancia="0.00")
    assert ganancia_realizada(c) == Decimal("40000.00")


def test_fiado_gana_la_diferencia_aunque_la_plata_no_haya_entrado() -> None:
    """Fiar reconoce la ganancia el día de la entrega (decisión del dueño): el
    cliente queda debiendo el neto, pero lo ganado ya está fijado."""
    c = _cheque(ChequeEstado.FIADO, monto="1000000", compra="12", venta="5")
    assert ganancia_realizada(c) == Decimal("70000.00")


def test_rechazado_no_devuelve_perdida() -> None:
    """El rebote va aparte y no se resta (decisión del dueño): el papel se le
    reclama al cliente y el desenlace todavía no se sabe. Lo que costó se mira
    con `neto_compra`, que es lo que el reporte muestra al lado."""
    c = _cheque(ChequeEstado.RECHAZADO, monto="1000000", compra="10")
    assert ganancia_realizada(c) == Decimal("0.00")
    assert neto_compra(c) == Decimal("900000.00")


def test_una_venta_sin_spread_no_inventa_ganancia() -> None:
    """Vendido al mismo porcentaje que se compró: no se ganó nada, y el dato
    tiene que decir cero y no el descuento de compra."""
    c = _cheque(ChequeEstado.VENDIDO, compra="10", venta="10", ganancia="0.00")
    assert ganancia_realizada(c) == Decimal("0.00")


def test_venta_a_perdida_resta() -> None:
    """Un cheque colocado más barato de lo que se compró deja ganancia negativa,
    y el reporte tiene que mostrarla en rojo, no esconderla en un cero."""
    c = _cheque(ChequeEstado.VENDIDO, compra="8", venta="10", ganancia="-20000.00")
    assert ganancia_realizada(c) == Decimal("-20000.00")
