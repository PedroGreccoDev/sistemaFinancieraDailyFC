"""Pagar con varios cheques de una (§2.c, §3).

"Me entregó estos tres al 5%" con la foto es la forma normal de cobrar: el
cliente junta los papeles que tiene y con eso salda. Dos reglas:

1. **Cada papel entra a cartera por separado** —vence y se cobra por su cuenta—
   pero la deuda baja **una sola vez, por la suma de los netos**. Si se sumaran
   los nominales se le estaría regalando el descuento en cada cobro.
2. **El mismo cheque no puede venir dos veces** en el mismo pago: es un número
   tipeado (o leído de la foto) dos veces, y cargarlo doble mete en cartera plata
   que no existe.

Unitarios puros: la aritmética vive en los schemas y el rechazo del repetido en
el helper de alta, así que no hace falta BD para custodiar ninguna de las dos.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.schemas.cheques import ChequeEntregado, PagoConCheques
from app.schemas.deudores import CobroClienteChequeCreate
from app.schemas.prestamos import PrestamoPagarConChequeRequest
from app.services.exceptions import ValidationError


def _tres_al_cinco() -> list[dict]:
    return [
        {"nro_cheque": "00081001", "banco": "Galicia", "monto": "500000", "porcentaje_compra": "5"},
        {"nro_cheque": "00081002", "banco": "Galicia", "monto": "700000", "porcentaje_compra": "5"},
        {"nro_cheque": "00081003", "banco": "Nación", "monto": "300000", "porcentaje_compra": "5"},
    ]


def test_lo_que_salda_es_la_suma_de_los_netos() -> None:
    pago = PagoConCheques(cheques=_tres_al_cinco())

    # Nominal 1.500.000 al 5% → 1.425.000. Acreditar el nominal sería regalarle
    # 75.000 al cliente en un solo cobro.
    assert pago.valor_neto_total == Decimal("1425000.00")


def test_cada_cheque_lleva_su_propio_descuento() -> None:
    """Uno a 30 días y otro a 90 no se toman al mismo porcentaje."""
    pago = PagoConCheques(cheques=[
        {"nro_cheque": "A1", "monto": "1000000", "porcentaje_compra": "5"},
        {"nro_cheque": "A2", "monto": "1000000", "porcentaje_compra": "12"},
    ])

    assert pago.valor_neto_total == Decimal("1830000.00")  # 950.000 + 880.000


def test_la_forma_vieja_de_un_cheque_solo_sigue_andando() -> None:
    """Un mensaje dictado sin foto trae uno, y el panel viejo mandaba así."""
    pago = PagoConCheques(
        nro_cheque_pago="00099001",
        banco_pago="Galicia",
        monto_cheque=Decimal("500000"),
        porcentaje_compra_cheque=Decimal("10"),
    )

    assert len(pago.cheques) == 1
    assert pago.cheques[0].nro_cheque == "00099001"
    assert pago.valor_neto_total == Decimal("450000.00")


def test_sin_cheque_no_hay_pago() -> None:
    with pytest.raises(ValueError):
        PagoConCheques()


def test_los_dos_cobros_de_cliente_hablan_el_mismo_idioma() -> None:
    """El cobro consolidado y el de un préstamo aceptan la lista igual.

    Si uno pidiera los cheques de otra forma, el bot tendría que armar dos
    payloads distintos para la misma frase del operador."""
    from uuid import uuid4

    from app.db.models import Moneda

    consolidado = CobroClienteChequeCreate(
        cliente_id=uuid4(), moneda_deuda=Moneda.ARS, cheques=_tres_al_cinco()
    )
    prestamo = PrestamoPagarConChequeRequest(cheques=_tres_al_cinco())

    assert consolidado.valor_neto_total == Decimal("1425000.00")
    assert sum((c.valor_neto for c in prestamo.cheques), Decimal("0.00")) == Decimal("1425000.00")


def test_el_mismo_papel_dos_veces_en_el_mismo_pago_se_rechaza() -> None:
    """Pasa con la foto: el modelo lee dos veces el cheque de arriba de la pila."""
    from app.services.cheques import ingresar_cheques_de_pago

    repetidos = [
        ChequeEntregado(nro_cheque="00081001", banco="Galicia", monto=Decimal("500000"), porcentaje_compra=Decimal("5")),
        ChequeEntregado(nro_cheque="00081001", banco="Galicia", monto=Decimal("500000"), porcentaje_compra=Decimal("5")),
    ]

    class DB:
        def scalar(self, _stmt):  # noqa: ANN001, ANN202
            return None  # ninguno está en cartera

        def add(self, _obj) -> None:  # noqa: ANN001
            pass

        def flush(self) -> None:
            pass

    from uuid import uuid4

    with pytest.raises(ValidationError) as error:
        ingresar_cheques_de_pago(DB(), repetidos, cliente_id=uuid4())

    assert "dos veces" in str(error.value)
