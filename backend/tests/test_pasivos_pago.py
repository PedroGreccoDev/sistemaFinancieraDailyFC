from __future__ import annotations

from decimal import Decimal

import pytest

from app.db.models import Moneda
from app.services.exceptions import ValidationError
from app.services.pasivos import calcular_reduccion_saldo


def _red(
    moneda_deuda: Moneda,
    saldo: str,
    moneda_pago: Moneda,
    monto_pagado: str,
    cotizacion: str | None = None,
) -> Decimal:
    return calcular_reduccion_saldo(
        moneda_deuda,
        Decimal(saldo),
        moneda_pago,
        Decimal(monto_pagado),
        None if cotizacion is None else Decimal(cotizacion),
    )


def test_misma_moneda_reduccion_directa() -> None:
    # Deuda USD 100, paga USD 40 → baja USD 40 (la cotización es irrelevante).
    assert _red(Moneda.USD, "100", Moneda.USD, "40") == Decimal("40.00")


def test_misma_moneda_ignora_cotizacion() -> None:
    assert _red(Moneda.ARS, "100000", Moneda.ARS, "60000", "1200") == Decimal("60000.00")


def test_deuda_usd_pagada_en_pesos() -> None:
    # Deuda USD 100, paga $120.000 @ 1200 → salda USD 100 (cancela).
    assert _red(Moneda.USD, "100", Moneda.ARS, "120000", "1200") == Decimal("100.00")


def test_deuda_usd_pagada_en_pesos_parcial() -> None:
    # Paga $60.000 @ 1200 → salda USD 50.
    assert _red(Moneda.USD, "100", Moneda.ARS, "60000", "1200") == Decimal("50.00")


def test_deuda_ars_pagada_en_usd() -> None:
    # Deuda ARS 120.000, paga USD 100 @ 1200 → salda $120.000 (cancela).
    assert _red(Moneda.ARS, "120000", Moneda.USD, "100", "1200") == Decimal("120000.00")


def test_cross_sin_cotizacion_falla() -> None:
    with pytest.raises(ValidationError):
        _red(Moneda.USD, "100", Moneda.ARS, "120000", None)


def test_cross_cotizacion_cero_falla() -> None:
    with pytest.raises(ValidationError):
        _red(Moneda.USD, "100", Moneda.ARS, "120000", "0")


def test_pago_supera_saldo_falla() -> None:
    # Deuda USD 100, paga $150.000 @ 1200 → equivale a USD 125 > 100.
    with pytest.raises(ValidationError):
        _red(Moneda.USD, "100", Moneda.ARS, "150000", "1200")


def test_exceso_de_un_centavo_cancela_exacto() -> None:
    # 120012 / 1200 = 100.01 → excede el saldo (100.00) por 1 centavo → cancela exacto.
    assert _red(Moneda.USD, "100", Moneda.ARS, "120012", "1200") == Decimal("100.00")


def test_exceso_mayor_a_un_centavo_falla() -> None:
    # 120100 / 1200 = 100.08.. → excede por más de un centavo → error.
    with pytest.raises(ValidationError):
        _red(Moneda.USD, "100", Moneda.ARS, "120100", "1200")
