from __future__ import annotations

from decimal import Decimal

from app.services.deudas_simples import aplicar_cobro


def _cobro(saldo: str, reduccion: str) -> tuple[Decimal, bool]:
    return aplicar_cobro(Decimal(saldo), Decimal(reduccion))


def test_cobro_parcial_no_cancela() -> None:
    # Deuda 100.000, se cobra 40.000 → queda 60.000, sigue abierta.
    nuevo, cancelada = _cobro("100000", "40000")
    assert nuevo == Decimal("60000.00")
    assert cancelada is False


def test_cobro_total_cancela() -> None:
    # Se cobra exactamente el saldo → queda en 0 y cancela.
    nuevo, cancelada = _cobro("100000", "100000")
    assert nuevo == Decimal("0.00")
    assert cancelada is True


def test_cobro_deja_centavos() -> None:
    nuevo, cancelada = _cobro("100.50", "0.50")
    assert nuevo == Decimal("100.00")
    assert cancelada is False


def test_reduccion_topeada_cancela() -> None:
    # calcular_reduccion_saldo ya topea la reducción al saldo; aplicar_cobro sobre
    # ese tope (reduccion == saldo) siempre cancela y nunca deja saldo negativo.
    nuevo, cancelada = _cobro("33333.33", "33333.33")
    assert nuevo == Decimal("0.00")
    assert cancelada is True
