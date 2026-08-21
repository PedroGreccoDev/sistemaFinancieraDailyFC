"""Comprar sin abonar: qué sale de la caja y qué queda como deuda.

El negocio compra a crédito —un lote de dólares o un cheque que se paga después—
y esa plata **no salió de la caja**. Lo que se custodia acá es el reparto entre
las dos cosas y las validaciones de carga, que es donde un error se vuelve un
egreso inventado (o una deuda que nadie anotó).

Ver §Comprar sin abonar.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.db.models import Moneda, MovimientoEfectivoTipo
from app.schemas.cheques import ChequeCreate
from app.schemas.movimientos import MovimientoEfectivoCreate
from app.services.exceptions import ValidationError
from app.services.pasivos import repartir_compra


def _rep(total: str, abonado: str | None) -> tuple[Decimal, Decimal]:
    return repartir_compra(
        Decimal(total), None if abonado is None else Decimal(abonado)
    )


# ══════════════════════════════════════════════════════════════════════
#  El reparto: cuánto salió de la caja y cuánto se debe
# ══════════════════════════════════════════════════════════════════════

def test_sin_monto_abonado_se_pago_todo() -> None:
    # El default histórico: toda compra cargada hasta hoy salió entera de la caja.
    # Si esto cambiara, cada compra existente se convertiría en una deuda.
    assert _rep("1250000", None) == (Decimal("1250000.00"), Decimal("0.00"))


def test_compra_totalmente_a_deber_no_saca_nada_de_la_caja() -> None:
    assert _rep("1250000", "0") == (Decimal("0.00"), Decimal("1250000.00"))


def test_compra_parcial() -> None:
    # Paga $400.000 de un lote de $1.000.000: sale eso y se deben $600.000.
    assert _rep("1000000", "400000") == (Decimal("400000.00"), Decimal("600000.00"))


def test_abonar_el_total_no_deja_deuda() -> None:
    # Decir explícitamente que se pagó todo tiene que dar igual que no decir nada.
    assert _rep("900000", "900000") == (Decimal("900000.00"), Decimal("0.00"))


def test_no_se_puede_abonar_mas_que_el_total() -> None:
    # Pagar de más no es una compra a deber: es una carga equivocada.
    with pytest.raises(ValidationError):
        _rep("900000", "950000")


def test_no_se_puede_abonar_negativo() -> None:
    with pytest.raises(ValidationError):
        _rep("900000", "-1")


def test_las_partes_suman_el_total() -> None:
    # Lo que salió de la caja más lo que se debe es exactamente el precio: si no
    # cerrara, la diferencia sería plata que no está en ningún lado.
    abonado, a_deber = _rep("1234567.89", "333333.33")
    assert abonado + a_deber == Decimal("1234567.89")


# ══════════════════════════════════════════════════════════════════════
#  Compra de dólares: validación de la carga
# ══════════════════════════════════════════════════════════════════════

def _compra_usd(**extra) -> MovimientoEfectivoCreate:
    base = dict(
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=Decimal("1000.00"),
        cotizacion_aplicada=Decimal("1250"),
    )
    return MovimientoEfectivoCreate(**{**base, **extra})


def test_compra_usd_pagada_no_necesita_vendedor() -> None:
    # La compra de contado sigue funcionando igual que siempre, sin cliente.
    assert _compra_usd().monto_abonado is None


def test_compra_usd_a_deber_exige_vendedor() -> None:
    # Sin saber a quién se le debe no se puede armar el pasivo.
    with pytest.raises(PydanticValidationError):
        _compra_usd(monto_abonado=Decimal("0"))


def test_compra_usd_a_deber_con_vendedor_es_valida() -> None:
    mov = _compra_usd(monto_abonado=Decimal("0"), cliente_id=uuid4())
    assert mov.monto_abonado == Decimal("0")


def test_compra_usd_no_se_puede_abonar_mas_que_el_total() -> None:
    # 1000 USD @ 1250 son $1.250.000; abonar más es un error de tipeo.
    with pytest.raises(PydanticValidationError):
        _compra_usd(monto_abonado=Decimal("1250001"), cliente_id=uuid4())


def test_una_venta_no_puede_quedar_a_deber() -> None:
    # Si vendiste y te quedaron debiendo, el que debe es el cliente: eso es una
    # deuda de cliente (§2.b), no un pasivo del negocio. Tomarlo por acá anotaría
    # la deuda para el lado contrario.
    with pytest.raises(PydanticValidationError):
        MovimientoEfectivoCreate(
            tipo=MovimientoEfectivoTipo.VENTA,
            moneda=Moneda.USD,
            monto=Decimal("500.00"),
            cotizacion_aplicada=Decimal("1260"),
            monto_abonado=Decimal("0"),
            cliente_id=uuid4(),
        )


# ══════════════════════════════════════════════════════════════════════
#  Compra de cheque: validación de la carga
# ══════════════════════════════════════════════════════════════════════

def _cheque(**extra) -> ChequeCreate:
    base = dict(
        nro_cheque="12345",
        monto=Decimal("1000000.00"),
        porcentaje_compra=Decimal("10"),
    )
    return ChequeCreate(**{**base, **extra})


def test_cheque_a_deber_se_debe_el_neto_no_el_nominal() -> None:
    # Un cheque de $1.000.000 al 10% se compra por $900.000: eso es lo que se debe
    # si no se pagó. Abonar $900.000 es pagarlo entero.
    assert _cheque(monto_abonado=Decimal("900000"), cliente_origen_id=uuid4())

    # Y $900.001 ya supera lo que el cheque vale.
    with pytest.raises(PydanticValidationError):
        _cheque(monto_abonado=Decimal("900001"), cliente_origen_id=uuid4())


def test_cheque_a_deber_exige_vendedor() -> None:
    with pytest.raises(PydanticValidationError):
        _cheque(monto_abonado=Decimal("0"))


def test_cheque_pagado_no_necesita_vendedor() -> None:
    assert _cheque().monto_abonado is None


def test_neto_de_cheque_a_deber_coincide_con_el_reparto() -> None:
    # El servicio reparte contra el valor neto; el schema valida contra el mismo
    # número. Que se separen sería aceptar una carga que después falla al asentar.
    cheque = _cheque(monto_abonado=Decimal("400000"), cliente_origen_id=uuid4())
    neto = (
        cheque.monto * (Decimal("100") - cheque.porcentaje_compra) / Decimal("100")
    ).quantize(Decimal("0.01"))
    assert repartir_compra(neto, cheque.monto_abonado) == (
        Decimal("400000.00"),
        Decimal("500000.00"),
    )
