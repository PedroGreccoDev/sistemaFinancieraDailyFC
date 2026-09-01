"""El alta de un cheque muestra el nominal Y lo que vale.

El operador carga el cheque mirando la lámina: ahí está el nominal y ahí está el
número, pero el descuento lo dice el dueño de palabra y es el dato que más se
tipea mal. Con "Nominal: $1.000.000 / Compra: 10%" el operador tiene que hacer
la cuenta de cabeza para darse cuenta de que el bot entendió 10 y no 1, y en un
fajo de cuatro tendría que hacerla cuatro veces. Por eso la confirmación trae
los dos números ya resueltos: el nominal y el valor (nominal − descuento), que
es lo que se le paga al cliente que trajo el papel.

Unitario: no hay base. Se reemplaza el alta —lo único que toca la base— por un
cheque armado en memoria, y se mira el texto que sale.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Cheque, ChequeTipo
from app.services.whatsapp import dispatcher


def _cheque(monto: str, pct: str, nro: str | None = "00012345") -> Cheque:
    return Cheque(
        nro_cheque=nro,
        banco="Nación",
        monto=Decimal(monto),
        porcentaje_compra=Decimal(pct),
        fecha_pago=date(2026, 12, 1),
        tipo=ChequeTipo.PAPEL,
        monto_abonado=None,
    )


@pytest.fixture
def alta_falsa(monkeypatch):
    """Hace que `_alta_de_cheque` devuelva los cheques que le pasemos, en orden."""

    def _preparar(*cheques: Cheque) -> None:
        pendientes = list(cheques)

        def _alta(db, data, msg_at=None, foto=None):
            return pendientes.pop(0), []

        monkeypatch.setattr(dispatcher, "_alta_de_cheque", _alta)

    return _preparar


def test_un_cheque_muestra_nominal_y_valor(alta_falsa) -> None:
    alta_falsa(_cheque("1000000", "10"))
    ok, texto = dispatcher._registrar_un_cheque(None, {})
    assert ok
    assert "Nominal: $1.000.000" in texto
    # 10% de descuento sobre un millón: se le pagan $900.000 al cliente.
    assert "$900.000" in texto


def test_el_valor_sale_aunque_el_cheque_quede_a_deber(alta_falsa) -> None:
    """Si no se abonó nada, "Salió de caja" es $0 y el valor no se deduce de ahí:
    tiene que estar dicho aparte o el operador no ve qué se le queda debiendo."""
    ch = _cheque("1000000", "10")
    ch.monto_abonado = Decimal("0")
    alta_falsa(ch)
    _, texto = dispatcher._registrar_un_cheque(None, {})
    assert "vale $900.000" in texto
    assert "Salió de caja: $0" in texto
    assert "Queda a deber: $900.000" in texto


def test_un_fajo_muestra_el_valor_de_cada_cheque(alta_falsa) -> None:
    alta_falsa(_cheque("1000000", "10", "1"), _cheque("500000", "8", "2"))
    ok, texto = dispatcher._registrar_cheque(
        None,
        "549999",
        {"cheques": [{"nro_cheque": "1"}, {"nro_cheque": "2"}]},
    )
    assert ok
    assert "$1.000.000,00 → $900.000,00" in texto
    assert "$500.000,00 → $460.000,00" in texto
