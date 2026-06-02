from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    Cheque,
    ChequeEstado,
    FrecuenciaCuotas,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    Prestamo,
)
from app.services.prestamos import construir_cuotas


def test_cheque_entra_en_cartera_y_venta_calcula_spread() -> None:
    cheque = Cheque(
        nro_cheque="CHK-001",
        monto=Decimal("100000.00"),
        porcentaje_compra=Decimal("3.0000"),
        estado=ChequeEstado.EN_CARTERA,
    )

    cheque.transition_to(
        ChequeEstado.VENDIDO,
        operador_id="operador-1",
        motivo="Venta manual al 5%",
        porcentaje_venta=Decimal("5.0000"),
    )

    assert cheque.estado == ChequeEstado.VENDIDO
    assert cheque.ganancia == Decimal("2000.00")
    assert cheque.ultimo_operador_id == "operador-1"


def test_cheque_vendido_es_estado_terminal() -> None:
    cheque = Cheque(
        nro_cheque="CHK-002",
        monto=Decimal("50000.00"),
        porcentaje_compra=Decimal("2.5000"),
        estado=ChequeEstado.VENDIDO,
    )

    with pytest.raises(InvalidChequeStateTransition):
        cheque.transition_to(
            ChequeEstado.RECHAZADO,
            operador_id="operador-1",
            motivo="Intento invalido",
        )


def test_transicion_manual_exige_operador_y_motivo() -> None:
    cheque = Cheque(
        nro_cheque="CHK-003",
        monto=Decimal("25000.00"),
        porcentaje_compra=Decimal("1.0000"),
        estado=ChequeEstado.EN_CARTERA,
    )

    with pytest.raises(ManualOperationRequired):
        cheque.transition_to(
            ChequeEstado.COBRADO,
            operador_id="",
            motivo="Cobro manual",
        )


def test_cuotas_mensuales_respetan_fin_de_mes_y_redondeo() -> None:
    prestamo = Prestamo(
        credito=Decimal("1000.00"),
        total_a_cobrar=Decimal("1000.01"),
        cuotas=3,
        frecuencia=FrecuenciaCuotas.MENSUAL,
        fecha_inicio=date(2026, 1, 31),
    )

    cuotas = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=date(2026, 1, 31),
        cantidad=3,
        frecuencia=FrecuenciaCuotas.MENSUAL,
        total_a_cobrar=Decimal("1000.01"),
    )

    assert [cuota.fecha_vencimiento for cuota in cuotas] == [
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
    ]
    assert sum(cuota.monto for cuota in cuotas) == Decimal("1000.01")


def test_cuotas_quincenales_suman_total() -> None:
    prestamo = Prestamo(
        credito=Decimal("900.00"),
        total_a_cobrar=Decimal("1000.00"),
        cuotas=4,
        frecuencia=FrecuenciaCuotas.QUINCENAL,
        fecha_inicio=date(2026, 6, 2),
    )

    cuotas = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=date(2026, 6, 2),
        cantidad=4,
        frecuencia=FrecuenciaCuotas.QUINCENAL,
        total_a_cobrar=Decimal("1000.00"),
    )

    assert [cuota.fecha_vencimiento for cuota in cuotas] == [
        date(2026, 6, 17),
        date(2026, 7, 2),
        date(2026, 7, 17),
        date(2026, 8, 1),
    ]
    assert sum(cuota.monto for cuota in cuotas) == Decimal("1000.00")
