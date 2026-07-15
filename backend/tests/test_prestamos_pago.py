from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.models import Moneda
from app.services.conversion import calcular_reduccion_saldo
from app.services.exceptions import ValidationError
from app.services.prestamos import repartir_pago_en_cuotas


def _rep(saldos: list[str], monto: str) -> list[Decimal]:
    return repartir_pago_en_cuotas([Decimal(s) for s in saldos], Decimal(monto))


# ── repartir_pago_en_cuotas: imputación a las cuotas, de la más vieja primero ──

def test_reparte_total_exacto() -> None:
    # 3 cuotas de 20.000, paga 60.000 → llena las tres.
    assert _rep(["20000", "20000", "20000"], "60000") == [
        Decimal("20000.00"),
        Decimal("20000.00"),
        Decimal("20000.00"),
    ]


def test_reparte_parcial_deja_una_a_medias() -> None:
    # Paga 30.000 → salda la 1ª, media 2ª, nada a la 3ª.
    assert _rep(["20000", "20000", "20000"], "30000") == [
        Decimal("20000.00"),
        Decimal("10000.00"),
        Decimal("0.00"),
    ]


def test_reparte_menos_que_la_primera() -> None:
    assert _rep(["20000", "20000"], "5000") == [Decimal("5000.00"), Decimal("0.00")]


def test_reparte_saltea_cuotas_sin_saldo() -> None:
    # Una cuota ya saldada (saldo 0) no recibe nada; el pago sigue a la siguiente.
    assert _rep(["0", "20000"], "15000") == [Decimal("0.00"), Decimal("15000.00")]


def test_reparte_no_reparte_de_mas() -> None:
    # Si el monto excede el total de saldos, solo se aplica lo que hay.
    assert _rep(["10000"], "15000") == [Decimal("10000.00")]


def test_reparte_arranca_de_una_cuota_parcial() -> None:
    # Saldos ya reducidos por un pago previo (15.000 y 20.000). Paga 25.000.
    assert _rep(["15000", "20000"], "25000") == [
        Decimal("15000.00"),
        Decimal("10000.00"),
    ]


# ── El pago del préstamo reutiliza el mismo cross-currency que pasivos/fiados ──

def test_prestamo_usd_pagado_en_pesos() -> None:
    # Préstamo con saldo USD 100, paga $60.000 @ 1200 → salda USD 50.
    assert calcular_reduccion_saldo(
        Moneda.USD, Decimal("100"), Moneda.ARS, Decimal("60000"), Decimal("1200")
    ) == Decimal("50.00")


def test_prestamo_ars_pagado_en_usd_cancela() -> None:
    # Préstamo con saldo ARS 120.000, paga USD 100 @ 1200 → cancela.
    assert calcular_reduccion_saldo(
        Moneda.ARS, Decimal("120000"), Moneda.USD, Decimal("100"), Decimal("1200")
    ) == Decimal("120000.00")


def test_prestamo_cross_sin_cotizacion_falla() -> None:
    with pytest.raises(ValidationError):
        calcular_reduccion_saldo(
            Moneda.USD, Decimal("100"), Moneda.ARS, Decimal("60000"), None
        )
