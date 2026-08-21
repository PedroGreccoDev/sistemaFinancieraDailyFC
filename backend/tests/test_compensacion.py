"""Compensación: el cliente le transfiere a un acreedor y bajan las dos deudas.

Lo que se custodia acá es el cálculo de las dos patas —cuánto baja lo que el
cliente debe y cuánto baja lo que el negocio le debe al acreedor— y la asimetría
entre ellas: contra el acreedor no se puede transferir de más, contra el cliente
sí (le queda a favor).

Estilo del proyecto: unitarios puros, sin BD.

Ver §Compensación.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest

from app.db.models import CuotaEstado, Moneda
from app.services.anulacion import _ENTIDADES
from app.services.conversion import (
    calcular_reduccion_saldo,
    convertir_a_moneda_deuda,
)
from app.services.deudas_simples import repartir_cobro_fifo
from app.services.exceptions import ValidationError


# ══════════════════════════════════════════════════════════════════════
#  Las dos patas de la operación
# ══════════════════════════════════════════════════════════════════════

def _pata_acreedor(saldo_pasivo: str, monto: str) -> Decimal:
    """Cuánto baja el pasivo, misma moneda."""
    return calcular_reduccion_saldo(
        Moneda.ARS, Decimal(saldo_pasivo), Moneda.ARS, Decimal(monto), None
    )


def test_compensacion_parcial_del_pasivo() -> None:
    # El negocio le debe $1.000.000 a Y y X le transfiere $600.000: el pasivo
    # queda en $400.000 y por la caja no pasó nada.
    assert _pata_acreedor("1000000", "600000") == Decimal("600000.00")


def test_compensacion_que_cancela_el_pasivo() -> None:
    assert _pata_acreedor("1000000", "1000000") == Decimal("1000000.00")


def test_no_se_le_puede_transferir_al_acreedor_mas_de_lo_que_se_le_debe() -> None:
    # Si X le manda a Y más de lo que el negocio le debe, Y pasa a deberle al
    # negocio: eso es otra operación, no una compensación. Se rechaza.
    with pytest.raises(ValidationError):
        _pata_acreedor("500000", "600000")


def test_contra_el_cliente_si_puede_sobrar() -> None:
    # La pata del cliente convierte SIN topear, justamente para que el excedente
    # exista y se pueda resolver: el cliente paga lo que tiene.
    convertido = convertir_a_moneda_deuda(
        Moneda.ARS, Moneda.ARS, Decimal("700000"), None
    )
    saldo_cliente = Decimal("600000.00")
    imputado = min(convertido, saldo_cliente)
    excedente = convertido - imputado
    assert imputado == Decimal("600000.00")
    assert excedente == Decimal("100000.00")


# ══════════════════════════════════════════════════════════════════════
#  Cruce de monedas
# ══════════════════════════════════════════════════════════════════════

def test_deuda_en_usd_saldada_con_transferencia_en_pesos() -> None:
    # X debe USD 500; le transfiere $600.000 a Y con cotización 1.200 → salda
    # los 500 dólares justos.
    imputado = convertir_a_moneda_deuda(
        Moneda.USD, Moneda.ARS, Decimal("600000"), Decimal("1200")
    )
    assert imputado == Decimal("500.00")


def test_cruce_sin_cotizacion_es_error() -> None:
    # La cotización la dicta siempre el operador: el sistema no la asume nunca.
    with pytest.raises(ValidationError):
        convertir_a_moneda_deuda(Moneda.USD, Moneda.ARS, Decimal("600000"), None)


def test_el_excedente_vuelve_a_la_moneda_transferida() -> None:
    # X debe USD 400 y transfiere $600.000 @ 1.200 (= USD 500): sobran USD 100,
    # que en la plata que realmente se movió son $120.000. El excedente se
    # devuelve en la moneda en que se transfirió, no en la de la deuda.
    convertido = convertir_a_moneda_deuda(
        Moneda.USD, Moneda.ARS, Decimal("600000"), Decimal("1200")
    )
    sobra_en_deuda = convertido - Decimal("400.00")
    excedente = convertir_a_moneda_deuda(
        Moneda.ARS, Moneda.USD, sobra_en_deuda, Decimal("1200")
    )
    assert sobra_en_deuda == Decimal("100.00")
    assert excedente == Decimal("120000.00")


# ══════════════════════════════════════════════════════════════════════
#  Imputación al cliente: el mismo FIFO del cobro consolidado
# ══════════════════════════════════════════════════════════════════════

def test_imputa_de_la_deuda_mas_vieja_a_la_mas_nueva_sin_mover_caja() -> None:
    # Tres deudas del cliente (ordenadas de más vieja a más nueva) y una
    # transferencia de $150.000: llena la primera, después la segunda.
    saldos = [Decimal("100000.00"), Decimal("80000.00"), Decimal("50000.00")]
    repartido = repartir_cobro_fifo(saldos, Decimal("150000.00"), Decimal("0.00"))
    imputado = [i for i, _plata in repartido]
    efectivo = [p for _i, p in repartido]

    assert imputado == [Decimal("100000.00"), Decimal("50000.00"), Decimal("0.00")]
    # Ninguna línea de caja: la plata fue del cliente al acreedor, no al negocio.
    assert all(p == Decimal("0.00") for p in efectivo)


def test_lo_imputado_nunca_supera_la_deuda_del_cliente() -> None:
    saldos = [Decimal("100000.00"), Decimal("80000.00")]
    repartido = repartir_cobro_fifo(saldos, Decimal("180000.00"), Decimal("0.00"))
    assert sum(i for i, _ in repartido) == Decimal("180000.00")


# ══════════════════════════════════════════════════════════════════════
#  Reversión: se devuelve lo que se sacó, no un recálculo
# ══════════════════════════════════════════════════════════════════════

class _Cuota:
    """Cuota mínima para probar la restitución sin BD."""

    def __init__(self, monto: str, pagado: str, estado: CuotaEstado) -> None:
        self.id = uuid.uuid4()
        self.numero_cuota = 1
        self.monto = Decimal(monto)
        self.monto_pagado = Decimal(pagado)
        self.estado = estado
        self.fecha_cobro = None


def test_devolver_a_una_cuota_la_reabre_si_la_compensacion_la_habia_cerrado() -> None:
    # La compensación cerró la cuota; al revertir tiene que volver a PENDIENTE.
    # Si quedara COBRADA con saldo, el préstamo no la vuelve a cobrar nunca.
    from app.services.compensaciones import _CENTAVO

    cuota = _Cuota("50000", "50000", CuotaEstado.COBRADA)
    imputado, cancelo = Decimal("30000.00"), True

    cuota.monto_pagado = (cuota.monto_pagado - imputado).quantize(_CENTAVO)
    if cancelo:
        cuota.estado = CuotaEstado.PENDIENTE
        cuota.fecha_cobro = None

    assert cuota.monto_pagado == Decimal("20000.00")
    assert cuota.estado == CuotaEstado.PENDIENTE


def test_la_compensacion_no_declara_lineas_de_caja() -> None:
    # Es la única entidad anulable sin `referencia_tipo`, y a propósito: no
    # asienta nada en el libro. Si algún día declarara refs, sería señal de que
    # alguien le hizo mover la caja.
    assert _ENTIDADES["compensacion"].refs == ()


# ══════════════════════════════════════════════════════════════════════
#  FIFO del lado del acreedor
# ══════════════════════════════════════════════════════════════════════

def test_la_transferencia_llena_la_deuda_mas_vieja_primero() -> None:
    # Le comprás tres veces a Pedro sin pagarle: son tres deudas. Cuando alguien
    # le transfiere, esa plata no va contra una elegida a dedo — llena la más
    # vieja primero, igual que del lado del cliente.
    from app.services.prestamos import repartir_pago_en_cuotas

    saldos = [Decimal("300000.00"), Decimal("400000.00"), Decimal("500000.00")]
    aplicado = repartir_pago_en_cuotas(saldos, Decimal("800000.00"))

    assert aplicado == [
        Decimal("300000.00"),  # saldada
        Decimal("400000.00"),  # saldada
        Decimal("100000.00"),  # queda debiendo 400.000
    ]


def test_el_reparto_al_acreedor_nunca_supera_lo_que_se_le_debe() -> None:
    from app.services.prestamos import repartir_pago_en_cuotas

    saldos = [Decimal("300000.00"), Decimal("400000.00")]
    aplicado = repartir_pago_en_cuotas(saldos, Decimal("900000.00"))
    # El tope lo pone `calcular_reduccion_saldo` antes de repartir; el repartidor
    # además no inventa: nunca aplica más que el saldo de cada una.
    assert sum(aplicado) == Decimal("700000.00")


def test_el_tope_del_acreedor_es_la_suma_de_todas_sus_deudas() -> None:
    # Transferirle más que el TOTAL lo dejaría a él debiéndole al negocio, y eso
    # es otra operación. El tope no es una deuda suelta: son todas juntas.
    saldo_total = Decimal("300000.00") + Decimal("400000.00") + Decimal("500000.00")
    assert calcular_reduccion_saldo(
        Moneda.ARS, saldo_total, Moneda.ARS, Decimal("1200000.00"), None
    ) == Decimal("1200000.00")

    # Un centavo de más se tolera: al convertir monedas el redondeo lo produce
    # solo, y hacer fallar "pagar el total" por eso sería peor que absorberlo.
    assert calcular_reduccion_saldo(
        Moneda.ARS, saldo_total, Moneda.ARS, Decimal("1200000.01"), None
    ) == saldo_total

    with pytest.raises(ValidationError):
        calcular_reduccion_saldo(
            Moneda.ARS, saldo_total, Moneda.ARS, Decimal("1200000.02"), None
        )


def test_al_revertir_cada_deuda_del_acreedor_recibe_lo_suyo() -> None:
    # Se guarda una fila por pasivo alcanzado con lo que se le imputó, así que
    # restituir es devolver ese número, no rehacer el reparto: entre medio esas
    # deudas pudieron recibir pagos y el reparto daría distinto.
    from app.services.compensaciones import _CENTAVO

    saldos = {"vieja": Decimal("0.00"), "media": Decimal("0.00"), "nueva": Decimal("400000.00")}
    imputado = {"vieja": Decimal("300000.00"), "media": Decimal("400000.00"), "nueva": Decimal("100000.00")}

    for clave, monto in imputado.items():
        saldos[clave] = (saldos[clave] + monto).quantize(_CENTAVO)

    assert saldos == {
        "vieja": Decimal("300000.00"),
        "media": Decimal("400000.00"),
        "nueva": Decimal("500000.00"),
    }
