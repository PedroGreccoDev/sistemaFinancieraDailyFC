"""El desglose de gastos del reporte de cierre (§7).

El recuadro contesta "¿en qué se fue la plata?" agrupando por concepto. El
concepto es **texto libre**, así que agrupar es siempre una aproximación: lo que
se prueba acá es que la aproximación sea la correcta —juntar lo que es
evidentemente lo mismo y no juntar nada más—.
"""
from __future__ import annotations

from decimal import Decimal

from app.db.models import Moneda
from app.services.reportes import agrupar_gastos_por_concepto


def _linea(concepto: str | None, monto: str, moneda: Moneda = Moneda.ARS):
    return (concepto, moneda, Decimal(monto))


def test_suma_lo_gastado_en_la_misma_cosa() -> None:
    salida = agrupar_gastos_por_concepto(
        [_linea("Nafta", "45000"), _linea("Comida", "22000"), _linea("Nafta", "50000")]
    )
    assert [(g.concepto, g.total) for g in salida] == [
        ("Nafta", Decimal("95000.00")),
        ("Comida", Decimal("22000.00")),
    ]


def test_va_de_mayor_a_menor() -> None:
    """Lo que más se llevó va arriba: es la pregunta que se le hace al recuadro."""
    salida = agrupar_gastos_por_concepto(
        [_linea("Parking", "8000"), _linea("Insumos", "62000"), _linea("Comida", "22000")]
    )
    assert [g.concepto for g in salida] == ["Insumos", "Comida", "Parking"]


def test_mayusculas_y_espacios_no_parten_un_concepto_en_dos() -> None:
    """El operador tipea a mano: "Nafta", "nafta" y " NAFTA " son la misma cosa."""
    salida = agrupar_gastos_por_concepto(
        [_linea("Nafta", "1000"), _linea("nafta", "2000"), _linea("  NAFTA ", "3000")]
    )
    assert len(salida) == 1
    assert salida[0].total == Decimal("6000.00")


def test_se_muestra_como_lo_escribio_el_operador() -> None:
    """La grafía que se ve es la primera que apareció, no la normalizada: en
    pantalla tiene que leerse "Nafta", no "nafta"."""
    salida = agrupar_gastos_por_concepto([_linea("Nafta", "1000"), _linea("nafta", "2000")])
    assert salida[0].concepto == "Nafta"


def test_dos_conceptos_parecidos_NO_se_juntan() -> None:
    """"Nafta" y "Nafta YPF" quedan separados, y está bien: no hay forma de saber
    que son lo mismo, y adivinarlo juntaría gastos distintos sin que nadie lo note."""
    salida = agrupar_gastos_por_concepto([_linea("Nafta", "1000"), _linea("Nafta YPF", "2000")])
    assert len(salida) == 2


def test_las_monedas_no_se_suman_entre_si() -> None:
    """Mismo concepto en las dos monedas son dos renglones, como en toda la app."""
    salida = agrupar_gastos_por_concepto(
        [_linea("Envío", "1000"), _linea("Envío", "120", Moneda.USD)]
    )
    assert [(g.moneda, g.total) for g in salida] == [
        ("ARS", Decimal("1000.00")),
        ("USD", Decimal("120.00")),
    ]


def test_los_pesos_van_primero() -> None:
    """Aunque el gasto en dólares sea "más grande" de número: son escalas distintas
    y ordenarlas juntas pondría 200 USD arriba de $150.000."""
    salida = agrupar_gastos_por_concepto(
        [_linea("Envío", "200", Moneda.USD), _linea("Nafta", "150000")]
    )
    assert [g.moneda for g in salida] == ["ARS", "USD"]


def test_un_gasto_sin_concepto_no_desaparece() -> None:
    """Perderlo en silencio sería lo peor: el recuadro no sumaría lo mismo que los
    egresos de la caja de arriba, que salen del mismo libro."""
    salida = agrupar_gastos_por_concepto([_linea(None, "5000"), _linea("   ", "3000")])
    assert len(salida) == 1
    assert salida[0].concepto == "Sin concepto"
    assert salida[0].total == Decimal("8000.00")


def test_sin_gastos_no_hay_renglones() -> None:
    assert agrupar_gastos_por_concepto([]) == []
