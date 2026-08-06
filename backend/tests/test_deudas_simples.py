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


# ── Cobro con cheque (§2.b — punto 7 de la reunión 2026-08-06) ─────────

def _valor_neto(monto: str, porcentaje: str) -> Decimal:
    """Lo que realmente vale un cheque recibido: nominal menos el descuento."""
    return (
        Decimal(monto) * (Decimal("100") - Decimal(porcentaje)) / Decimal("100")
    ).quantize(Decimal("0.01"))


def test_el_cheque_salda_por_su_valor_neto_no_por_el_nominal() -> None:
    """Un cheque de $100.000 al 10% vale $90.000. Si se imputara el nominal, la
    deuda quedaría saldada de más y el cliente pagaría menos de lo que debe."""
    assert _valor_neto("100000", "10") == Decimal("90000.00")


def test_cheque_que_cubre_justo_cancela_la_deuda() -> None:
    neto = _valor_neto("100000", "10")  # 90.000
    nuevo, cancelada = aplicar_cobro(Decimal("90000.00"), neto)
    assert nuevo == Decimal("0.00")
    assert cancelada is True


def test_cheque_insuficiente_deja_el_resto_a_deber() -> None:
    # Deuda 150.000, cheque neto 90.000 → siguen debiendo 60.000.
    neto = _valor_neto("100000", "10")
    nuevo, cancelada = aplicar_cobro(Decimal("150000.00"), neto)
    assert nuevo == Decimal("60000.00")
    assert cancelada is False


def test_cheque_de_mas_cancela_sin_dejar_saldo_negativo() -> None:
    """Un cheque que vale más que la deuda es el caso NORMAL: el cliente entrega
    el cheque que tiene, no uno recortado a medida. La deuda se cancela y la
    diferencia queda a favor del cliente.

    El servicio topea la imputación al saldo antes de llamar a `aplicar_cobro`
    (que por sí sola dejaría el saldo en negativo) e informa el excedente aparte.
    """
    saldo = Decimal("90000.00")
    neto = _valor_neto("200000", "10")  # 180.000 — el doble de la deuda

    diferencia = neto - saldo
    reduccion = min(neto, saldo)  # lo que hace cobrar_con_cheque
    nuevo, cancelada = aplicar_cobro(saldo, reduccion)

    assert nuevo == Decimal("0.00")
    assert cancelada is True
    assert diferencia == Decimal("90000.00")  # el negocio le queda debiendo esto


def test_cobrar_con_cheque_no_rechaza_un_cheque_mayor_al_saldo() -> None:
    """Regresión: usar `calcular_reduccion_saldo` acá rompía el caso normal.

    Esa función valida que el pago no supere el saldo —correcto para efectivo—,
    así que un cheque de más habría sido rechazado con un error en vez de
    cancelar la deuda. El cobro con cheque usa `convertir_a_moneda_deuda`, que
    convierte sin topear ni validar."""
    from app.db.models import Moneda
    from app.services.conversion import calcular_reduccion_saldo, convertir_a_moneda_deuda
    from app.services.exceptions import ValidationError

    saldo, neto = Decimal("90000.00"), Decimal("180000.00")

    # La función del efectivo rechaza este caso...
    try:
        calcular_reduccion_saldo(Moneda.ARS, saldo, Moneda.ARS, neto, None)
        raise AssertionError("debería haber rechazado un pago mayor al saldo")
    except ValidationError:
        pass

    # ...y la del cheque lo convierte sin drama.
    assert convertir_a_moneda_deuda(Moneda.ARS, Moneda.ARS, neto, None) == neto


def test_deuda_en_usd_cobrada_con_cheque_convierte_por_cotizacion() -> None:
    """Los cheques son siempre en pesos: pagar una deuda en USD con un cheque
    cruza monedas, y la cotización define cuántos dólares salda."""
    from app.services.conversion import calcular_reduccion_saldo
    from app.db.models import Moneda

    neto = _valor_neto("1000000", "0")  # $1.000.000 de cheque
    reduccion = calcular_reduccion_saldo(
        Moneda.USD, Decimal("1000.00"), Moneda.ARS, neto, Decimal("1000")
    )
    assert reduccion == Decimal("1000.00")  # 1.000.000 / 1.000 = 1.000 USD
