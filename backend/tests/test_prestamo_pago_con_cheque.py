"""Pagar un préstamo entregando un cheque (§3).

El cliente no entrega plata: entrega un papel. Dos reglas que no se pueden
perder de vista, las dos definidas por el dueño:

1. **Se acredita el neto, no el nominal.** "Me entregó este cheque al 5%" salda
   `nominal × (1 − 5%)`. Acreditar el nominal le regalaría el descuento al
   cliente en cada cobro, y es plata que no vuelve.
2. **El sobrante lo decide el operador.** Un cheque no se recorta a medida y casi
   nunca vale justo lo que se debe. Si sobra, la operación se rechaza hasta que
   diga qué hacer: bajarlo del capital (solo interés fijo), devolverlo en
   efectivo o quedar debiéndolo.

Unitarios: la BD es un stand-in que devuelve el préstamo pedido. Lo que se
custodia es la aritmética y la decisión, no el SQL.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    Cliente,
    Cuota,
    CuotaEstado,
    Moneda,
    Prestamo,
    PrestamoEstado,
    PrestamoTipo,
)
from app.schemas.prestamos import PrestamoPagarConChequeRequest
from app.services import prestamos as svc
from app.services.exceptions import ValidationError


class Commiteo(Exception):
    """El stand-in llegó hasta el commit: la operación se decidió sin preguntar."""


class DB:
    """Devuelve el préstamo en la primera consulta y nada en las siguientes.

    La segunda es la que busca un cheque con el mismo número en cartera: `None`
    significa "ese papel no está", que es el caso normal. `commit` corta acá con
    `Commiteo` —no hay base de verdad detrás— y los saldos quedan en los objetos
    para poder mirarlos.
    """

    def __init__(self, prestamo: Prestamo) -> None:
        self._respuestas = [prestamo]

    def scalar(self, _stmt):  # noqa: ANN001, ANN202
        return self._respuestas.pop(0) if self._respuestas else None

    def add(self, _obj) -> None:  # noqa: ANN001
        pass

    def flush(self) -> None:
        pass

    def commit(self) -> None:
        raise Commiteo


def _prestamo_interes_fijo(interes: str = "500000.00", capital: str = "5000000.00") -> Prestamo:
    p = Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        tipo_prestamo=PrestamoTipo.INTERES_FIJO,
        credito=Decimal(capital),
        capital_pendiente=Decimal(capital),
        monto_interes_fijo=Decimal(interes),
        dia_cobro=date(2026, 8, 28),
        moneda=Moneda.ARS,
        cuotas=0,
        total_a_cobrar=Decimal(capital),
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 7, 29),
    )
    p.cliente = Cliente(id=p.cliente_id, nombre="Pedrón")
    p.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=p.id,
            numero_cuota=1,
            fecha_vencimiento=date(2026, 8, 28),
            monto=Decimal(interes),
            monto_pagado=Decimal("0.00"),
            estado=CuotaEstado.PENDIENTE,
        )
    ]
    return p


def _pago(monto: str, pct: str, **kw) -> PrestamoPagarConChequeRequest:
    return PrestamoPagarConChequeRequest(
        nro_cheque="00077001",
        banco="Galicia",
        monto=Decimal(monto),
        porcentaje_compra=Decimal(pct),
        **kw,
    )


def test_el_cheque_que_sobra_no_se_imputa_solo() -> None:
    """La regla del dueño: "no puede haber errores de cobro".

    Un cheque de 3 millones al 5% entrega 2.850.000 netos contra 500.000 de
    interés. Los 2.350.000 que sobran pueden terminar en tres lugares muy
    distintos —capital, caja o una deuda a favor del cliente— y el sistema no
    elige por él.
    """
    prestamo = _prestamo_interes_fijo()

    with pytest.raises(ValidationError) as error:
        svc.pagar_con_cheque(DB(prestamo), prestamo.id, _pago("3000000", "5"))

    mensaje = str(error.value)
    # El sobrante que anuncia tiene que ser sobre el NETO (2.850.000 − 500.000),
    # no sobre el nominal: si dijera 2.500.000 el operador decidiría sobre un
    # número que no existe.
    assert "2350000.00" in mensaje
    assert "capital" in mensaje  # es a interés fijo: las tres salidas


def test_en_un_prestamo_en_cuotas_el_sobrante_no_ofrece_capital() -> None:
    """No hay capital que bajar: el cuadro de cuotas ya lo incluye."""
    prestamo = Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        credito=Decimal("500000.00"),
        moneda=Moneda.ARS,
        cuotas=1,
        total_a_cobrar=Decimal("600000.00"),
        ganancia=Decimal("100000.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 7, 14),
    )
    prestamo.cliente = Cliente(id=prestamo.cliente_id, nombre="Kiosco")
    prestamo.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=prestamo.id,
            numero_cuota=1,
            fecha_vencimiento=date(2026, 8, 14),
            monto=Decimal("600000.00"),
            monto_pagado=Decimal("0.00"),
            estado=CuotaEstado.PENDIENTE,
        )
    ]

    with pytest.raises(ValidationError) as error:
        svc.pagar_con_cheque(DB(prestamo), prestamo.id, _pago("700000", "0"))

    mensaje = str(error.value)
    assert "100000.00" in mensaje
    assert "capital" not in mensaje


def test_un_cheque_que_no_alcanza_entra_por_el_neto_y_no_pregunta_nada() -> None:
    """Lo normal: el cheque no cubre todo, así que no hay nada que decidir.

    Y acá se ve la primera regla: 400.000 nominales al 5% acreditan **380.000**
    contra el interés, no 400.000. Los 120.000 que faltan se siguen debiendo.
    """
    prestamo = _prestamo_interes_fijo()

    with pytest.raises(Commiteo):  # llegó a impactar: no hubo pregunta
        svc.pagar_con_cheque(DB(prestamo), prestamo.id, _pago("400000", "5"))

    cuota = prestamo.cuotas_detalle[0]
    assert cuota.monto_pagado == Decimal("380000.00")
    assert cuota.estado == CuotaEstado.PENDIENTE
