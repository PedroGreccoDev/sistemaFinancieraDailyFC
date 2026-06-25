from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.exceptions import ValidationError
from app.services.movimientos import calcular_ganancia_fifo


def _lotes(*pares: tuple[str, str]) -> list[tuple[Decimal, Decimal]]:
    """Helper: construye lotes (costo_unitario, restante) en orden FIFO."""
    return [(Decimal(c), Decimal(r)) for c, r in pares]


def test_fifo_venta_consume_dos_lotes_completos() -> None:
    # Compra 100@1000 y 100@1100; vende 200@1150.
    # 100·(1150−1000)=15000 + 100·(1150−1100)=5000 = 20000.
    ganancia, consumos = calcular_ganancia_fifo(
        _lotes(("1000", "100"), ("1100", "100")), Decimal("200"), Decimal("1150")
    )
    assert ganancia == Decimal("20000.00")
    assert consumos == [Decimal("100"), Decimal("100")]


def test_fifo_venta_parcial_cruza_lotes() -> None:
    # Vende 150: toma 100 del lote viejo y 50 del nuevo (FIFO).
    # 100·150 + 50·50 = 15000 + 2500 = 17500.
    ganancia, consumos = calcular_ganancia_fifo(
        _lotes(("1000", "100"), ("1100", "100")), Decimal("150"), Decimal("1150")
    )
    assert ganancia == Decimal("17500.00")
    assert consumos == [Decimal("100"), Decimal("50")]


def test_fifo_consume_solo_el_lote_mas_viejo() -> None:
    ganancia, consumos = calcular_ganancia_fifo(
        _lotes(("1000", "100"), ("1100", "100")), Decimal("80"), Decimal("1150")
    )
    assert ganancia == Decimal("12000.00")  # 80·(1150−1000)
    assert consumos == [Decimal("80"), Decimal("0")]


def test_fifo_venta_a_perdida_da_ganancia_negativa() -> None:
    # Compró a 1200, vende a 1150 → pierde 50 por dólar.
    ganancia, consumos = calcular_ganancia_fifo(
        _lotes(("1200", "100")), Decimal("100"), Decimal("1150")
    )
    assert ganancia == Decimal("-5000.00")
    assert consumos == [Decimal("100")]


def test_fifo_stock_insuficiente_lanza_validation_error() -> None:
    with pytest.raises(ValidationError):
        calcular_ganancia_fifo(_lotes(("1000", "100")), Decimal("200"), Decimal("1150"))


def test_fifo_sin_lotes_y_venta_cero_no_rompe() -> None:
    ganancia, consumos = calcular_ganancia_fifo([], Decimal("0"), Decimal("1150"))
    assert ganancia == Decimal("0.00")
    assert consumos == []
