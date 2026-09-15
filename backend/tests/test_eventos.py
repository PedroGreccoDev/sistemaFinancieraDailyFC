"""El registro de operaciones: qué cambió, dicho como lo lee el operador.

Lo que se custodia acá es la parte pura: comparar la foto de antes contra el
objeto editado. Si esto se equivoca, el diario cuenta cambios que no pasaron —o
peor, se calla los que sí—.

Estilo del proyecto: unitarios puros, sin BD.

Ver §Historial unificado.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.db.models import Moneda
from app.services import eventos as svc


class _Gasto:
    """Doble mínimo: solo hacen falta atributos."""

    def __init__(self, concepto: str, monto: Decimal, moneda: Moneda, fecha: date) -> None:
        self.concepto = concepto
        self.monto = monto
        self.moneda = moneda
        self.fecha = fecha


_CAMPOS = {"concepto": "concepto", "monto": "monto", "moneda": "moneda", "fecha": "fecha"}


def _gasto() -> _Gasto:
    return _Gasto("nafta", Decimal("10000.00"), Moneda.ARS, date(2026, 7, 4))


def test_solo_se_cuenta_lo_que_cambio():
    # El panel reenvía el formulario entero cada vez que se guarda: si se
    # listaran todos los campos, el diario se llenaría de renglones que no
    # cuentan nada.
    gasto = _gasto()
    antes = svc.foto(gasto, _CAMPOS)
    gasto.monto = Decimal("12000.00")
    assert svc.cambios(antes, gasto, _CAMPOS) == ["monto: 10,000.00 → 12,000.00"]


def test_sin_cambios_no_hay_nada_que_contar():
    gasto = _gasto()
    antes = svc.foto(gasto, _CAMPOS)
    assert svc.cambios(antes, gasto, _CAMPOS) == []


def test_la_correccion_sin_cambios_no_se_registra(monkeypatch):
    # `correccion` con la lista vacía no escribe: un "se editó" sin diferencia
    # es ruido en el diario.
    assert svc.correccion(
        None, que="gasto", cambios=[], referencia_tipo="gasto",
        referencia_id=None,
    ) is None


def test_los_valores_se_muestran_como_los_lee_el_operador():
    gasto = _gasto()
    antes = svc.foto(gasto, _CAMPOS)
    gasto.moneda = Moneda.USD
    gasto.fecha = date(2026, 7, 5)
    gasto.concepto = ""
    cambios = svc.cambios(antes, gasto, _CAMPOS)
    # La moneda por su valor y no por `Moneda.USD`; la fecha en formato de acá;
    # lo vacío como una raya y no como `None`.
    assert "moneda: ARS → USD" in cambios
    assert "fecha: 04/07/2026 → 05/07/2026" in cambios
    assert "concepto: nafta → —" in cambios


def test_un_cheque_solo_se_nombra_entero_y_varios_por_numero():
    class _Ch:
        def __init__(self, nro):
            self.nro_cheque = nro
            self.banco = "Nación"
            self.monto = Decimal("1000.00")
            from app.db.models import ChequeTipo
            self.tipo = ChequeTipo.PAPEL

    assert svc.nombrar_cheques([_Ch("123")]) == "cheque Nº 123 — Nación"
    assert svc.nombrar_cheques([_Ch("1"), _Ch("2")]) == "2 cheques (Nº 1, Nº 2)"
