from __future__ import annotations

from decimal import Decimal

from app.db.models import Moneda
from app.services.deudas_simples import (
    aplicar_cobro,
    calcular_imputacion_y_vuelto,
    repartir_cobro_fifo,
)


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


# ── Cobro por cliente: reparto FIFO entre sus deudas ───────────────────

def _d(*valores: str) -> list[Decimal]:
    return [Decimal(v) for v in valores]


def test_reparto_llena_la_deuda_mas_vieja_primero() -> None:
    """El cobro entra por la deuda más vieja; la nueva recibe solo el resto."""
    repartido = repartir_cobro_fifo(
        _d("10000", "10000"), Decimal("12000"), Decimal("12000")
    )
    assert [imputa for imputa, _ in repartido] == _d("10000.00", "2000.00")


def test_reparto_no_toca_las_deudas_que_no_alcanza() -> None:
    # Un cobro chico se queda en la primera: las otras dos quedan intactas.
    repartido = repartir_cobro_fifo(
        _d("10000", "5000", "3000"), Decimal("4000"), Decimal("4000")
    )
    assert [imputa for imputa, _ in repartido] == _d("4000.00", "0.00", "0.00")


def test_reparto_no_reparte_mas_que_el_total_adeudado() -> None:
    """Si la reducción supera lo que el cliente debe, se imputa solo lo adeudado.

    En el servicio esto no debería pasar (`calcular_reduccion_saldo` ya topea al
    saldo total), pero la función no puede depender de eso: repartir de más
    dejaría una deuda con saldo negativo."""
    repartido = repartir_cobro_fifo(
        _d("1000", "1000"), Decimal("5000"), Decimal("5000")
    )
    assert sum((imputa for imputa, _ in repartido), Decimal("0.00")) == Decimal("2000.00")


def test_en_una_sola_moneda_la_linea_de_caja_es_lo_imputado() -> None:
    """Cobro en la misma moneda de la deuda: cada deuda asienta exactamente lo
    que se le imputó, sin prorrateo de por medio."""
    repartido = repartir_cobro_fifo(
        _d("10000", "10000"), Decimal("15000"), Decimal("15000")
    )
    assert repartido == [
        (Decimal("10000.00"), Decimal("10000.00")),
        (Decimal("5000.00"), Decimal("5000.00")),
    ]


def test_cross_moneda_las_lineas_suman_exactamente_lo_que_entro() -> None:
    """Tres deudas iguales pagadas con un importe que no divide justo.

    Prorratear y redondear cada línea daría 33,33 × 3 = 99,99 y **la caja del día
    cerraría un centavo abajo de lo que entró**. El residuo va a la última deuda
    alcanzada, así que la suma es exacta."""
    efectivo = Decimal("100.00")
    repartido = repartir_cobro_fifo(_d("10", "10", "10"), Decimal("30.00"), efectivo)

    assert [plata for _, plata in repartido] == _d("33.33", "33.33", "33.34")
    assert sum((plata for _, plata in repartido), Decimal("0.00")) == efectivo


def test_cross_moneda_reparte_proporcional_a_lo_imputado() -> None:
    """La deuda que absorbe el doble de saldo recibe el doble de la plata."""
    repartido = repartir_cobro_fifo(
        _d("200", "100"), Decimal("300.00"), Decimal("300000.00")
    )
    assert [plata for _, plata in repartido] == _d("200000.00", "100000.00")


def test_una_sola_deuda_alcanzada_se_lleva_todo_el_efectivo() -> None:
    repartido = repartir_cobro_fifo(
        _d("1000", "1000"), Decimal("400.00"), Decimal("560000.00")
    )
    assert repartido[0] == (Decimal("400.00"), Decimal("560000.00"))
    assert repartido[1] == (Decimal("0.00"), Decimal("0.00"))


def test_sin_saldo_no_imputa_ni_asienta_nada() -> None:
    """Sin nada que imputar no puede quedar ninguna línea de caja colgada."""
    repartido = repartir_cobro_fifo(_d("0.00", "0.00"), Decimal("500"), Decimal("500"))
    assert repartido == [(Decimal("0.00"), Decimal("0.00"))] * 2


# ── Cobro por cliente CON CHEQUE: imputación y vuelto ──────────────────

def _vuelto(saldo: str, neto: str, moneda: Moneda = Moneda.ARS, cotiz: str | None = None):
    return calcular_imputacion_y_vuelto(
        moneda, Decimal(saldo), Decimal(neto), Decimal(cotiz) if cotiz else None
    )


def test_el_cheque_que_no_alcanza_no_deja_vuelto() -> None:
    """Cheque neto de 25.000 contra 60.000 de deuda: salda lo que puede y el
    cliente sigue debiendo. No hay nada a su favor."""
    imputado, diferencia = _vuelto("60000", "25000")
    assert imputado == Decimal("25000")
    assert diferencia == Decimal("0.00")


def test_el_cheque_justo_no_deja_vuelto() -> None:
    imputado, diferencia = _vuelto("60000", "60000")
    assert imputado == Decimal("60000")
    assert diferencia == Decimal("0.00")


def test_el_cheque_de_mas_cancela_todo_y_el_resto_queda_a_favor() -> None:
    """El caso que pidió el dueño: el cheque cubre TODAS las deudas y sobra.

    Se imputa solo lo adeudado —nunca deja saldos negativos— y la diferencia
    pasa a favor del cliente: el negocio le queda debiendo esa plata."""
    imputado, diferencia = _vuelto("60000", "90000")
    assert imputado == Decimal("60000")
    assert diferencia == Decimal("30000.00")


def test_el_vuelto_de_una_deuda_en_usd_se_devuelve_en_pesos() -> None:
    """Las deudas pueden ser en dólares, pero el cheque es un instrumento en
    pesos: lo que sobra es plata en pesos y en pesos se paga el vuelto.

    Deuda 100 USD, cheque neto $150.000 a 1000 → salda los 100 USD y sobran
    50 USD, que son $50.000."""
    imputado, diferencia = _vuelto("100", "150000", Moneda.USD, "1000")
    assert imputado == Decimal("100")
    assert diferencia == Decimal("50000.00")


def test_el_cobro_con_cheque_no_reparte_efectivo() -> None:
    """El cheque no mueve la caja: entra a cartera y la plata se reconoce al
    venderlo o cobrarlo. El reparto imputa saldos pero no puede dejar ninguna
    línea de caja, ni siquiera en cero."""
    repartido = repartir_cobro_fifo(_d("10000", "20000"), Decimal("25000"), Decimal("0.00"))
    assert [imputa for imputa, _ in repartido] == _d("10000.00", "15000.00")
    assert all(plata == Decimal("0.00") for _, plata in repartido)
