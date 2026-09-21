"""El cheque que se le paga al vendedor en dólares.

El negocio compra un cheque en pesos —con su nominal y su descuento— pero paga
con billetes: "te lo tomo al 10,2%, te doy 4200 a 1555 y el resto en efectivo".
Lo que se custodia acá es **con qué se pagó**: cuántos pesos cubrieron los
dólares, cuántos salieron de la caja ARS y cuánto quedó a deber. Es el reparto
donde un error no rompe nada en el momento y descuadra **dos** cajas a la vez —la
de dólares alta por lo que se entregó, la de pesos baja por lo mismo—.

Ver §Cheque pagado en dólares.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError as PydanticValidationError

from app.db.models import Cheque, ChequeEstado
from app.schemas.cheques import ChequeCreate
from app.services import cheques as svc_cheques


def _cheque(
    monto: str,
    pct: str,
    *,
    usd: str | None = None,
    cotiz: str | None = None,
    abonado: str | None = None,
) -> Cheque:
    """Un cheque en memoria, sin base: alcanza para las cuentas del pago."""
    return Cheque(
        monto=Decimal(monto),
        porcentaje_compra=Decimal(pct),
        usd_entregados=None if usd is None else Decimal(usd),
        cotizacion_usd=None if cotiz is None else Decimal(cotiz),
        monto_abonado=None if abonado is None else Decimal(abonado),
        estado=ChequeEstado.EN_CARTERA,
    )


def _create(
    monto: str = "8000000",
    pct: str = "10.2",
    *,
    usd: str | None = None,
    cotiz: str | None = None,
    abonado: str | None = None,
    con_vendedor: bool = True,
) -> ChequeCreate:
    return ChequeCreate(
        nro_cheque="12345",
        banco="Nación",
        monto=Decimal(monto),
        porcentaje_compra=Decimal(pct),
        cliente_origen_id=uuid4() if con_vendedor else None,
        usd_entregados=None if usd is None else Decimal(usd),
        cotizacion_usd=None if cotiz is None else Decimal(cotiz),
        monto_abonado=None if abonado is None else Decimal(abonado),
    )


# ══════════════════════════════════════════════════════════════════════
#  Con qué se pagó: dólares, pesos y lo que quedó a deber
# ══════════════════════════════════════════════════════════════════════

def test_los_dolares_cubren_su_parte_y_el_resto_sale_en_pesos() -> None:
    # El caso del dueño: cheque de $8.000.000 al 10,2% → vale $7.184.000. Le da
    # 4200 dólares a 1555 ($6.531.000) y los $653.000 que faltan, en efectivo.
    cheque = _cheque("8000000", "10.2", usd="4200", cotiz="1555")
    en_usd, en_pesos, a_deber = svc_cheques.partes_del_pago(cheque)

    assert svc_cheques.neto_compra(cheque) == Decimal("7184000.00")
    assert en_usd == Decimal("6531000.00")
    assert en_pesos == Decimal("653000.00")
    assert a_deber == Decimal("0.00")


def test_sin_dolares_se_paga_como_siempre() -> None:
    # La compra de toda la vida no cambia de significado: sin dólares, el valor
    # neto entero sale de la caja en pesos.
    en_usd, en_pesos, a_deber = svc_cheques.partes_del_pago(_cheque("1000000", "10"))
    assert (en_usd, en_pesos, a_deber) == (
        Decimal("0.00"), Decimal("900000.00"), Decimal("0.00")
    )


def test_los_dolares_pueden_cubrir_el_cheque_entero() -> None:
    # 600 USD a 1500 = $900.000, justo el neto: no sale un peso de la caja ARS y
    # no queda nada debiéndose.
    cheque = _cheque("1000000", "10", usd="600", cotiz="1500")
    assert svc_cheques.partes_del_pago(cheque) == (
        Decimal("900000.00"), Decimal("0.00"), Decimal("0.00")
    )


def test_lo_que_no_cubren_los_dolares_ni_los_pesos_queda_a_deber() -> None:
    # Le da 400 USD a 1500 ($600.000) y $100.000: de los $900.000 que vale el
    # cheque quedan $200.000 debiéndose al vendedor.
    cheque = _cheque("1000000", "10", usd="400", cotiz="1500", abonado="100000")
    assert svc_cheques.partes_del_pago(cheque) == (
        Decimal("600000.00"), Decimal("100000.00"), Decimal("200000.00")
    )


def test_solo_dolares_y_el_resto_a_deber() -> None:
    # "Le di 400 dólares y el resto se lo debo": monto_abonado en 0 es lo que
    # distingue el resto debido de un resto pagado en efectivo.
    cheque = _cheque("1000000", "10", usd="400", cotiz="1500", abonado="0")
    assert svc_cheques.partes_del_pago(cheque) == (
        Decimal("600000.00"), Decimal("0.00"), Decimal("300000.00")
    )


def test_la_cotizacion_del_cheque_es_la_pactada_no_la_del_mercado() -> None:
    # Lo que cubrieron los dólares se calcula con la cotización guardada en el
    # cheque: es el precio que las dos partes arreglaron ese día, y no se
    # recalcula nunca contra ninguna referencia.
    cheque = _cheque("1000000", "10", usd="500", cotiz="1000")
    assert svc_cheques.cubierto_en_usd(cheque) == Decimal("500000.00")
    cheque.cotizacion_usd = Decimal("1800")
    assert svc_cheques.cubierto_en_usd(cheque) == Decimal("900000.00")


# ══════════════════════════════════════════════════════════════════════
#  Lo que el alta no deja pasar
# ══════════════════════════════════════════════════════════════════════

def test_los_dolares_no_pueden_pasarse_del_valor_del_cheque() -> None:
    # Pagar de más falla, no se acomoda (decisión del dueño): 5000 USD a 1555 son
    # $7.775.000 contra un cheque que vale $7.184.000. Es un dedazo en los
    # dólares o en la cotización, y acomodarlo dejaría el cheque "comprado" por
    # un precio que nadie pactó.
    with pytest.raises(PydanticValidationError, match="se pasan"):
        _create(usd="5000", cotiz="1555")


def test_dolares_sin_cotizacion_no_entran() -> None:
    # Sin el precio pactado no hay forma de saber cuánto del cheque cubrieron.
    # El bot tiene prohibido inventarlo: pregunta (regla 1).
    with pytest.raises(PydanticValidationError, match="a cuánto"):
        _create(usd="4200")


def test_cotizacion_sin_dolares_tampoco() -> None:
    # Una cotización sola no significa nada, y guardarla haría creer que esa
    # compra pagó billetes que nunca salieron del cajón.
    with pytest.raises(PydanticValidationError, match="dólares"):
        _create(cotiz="1555")


def test_los_pesos_no_pueden_superar_lo_que_falta_tras_los_dolares() -> None:
    # Los dólares ya cubrieron $6.531.000 de los $7.184.000: en pesos solo
    # quedan $653.000. Abonar un millón es el mismo dedazo que abonar de más en
    # una compra sin dólares.
    with pytest.raises(PydanticValidationError, match="falta pagar"):
        _create(usd="4200", cotiz="1555", abonado="1000000")


def test_lo_que_queda_debiendo_necesita_vendedor() -> None:
    # La deuda tiene que quedar a nombre de alguien: es un pasivo real.
    with pytest.raises(PydanticValidationError, match="vendedor"):
        _create(usd="4200", cotiz="1555", abonado="0", con_vendedor=False)


def test_pagado_en_dolares_y_pesos_no_necesita_vendedor() -> None:
    # Pagado del todo no hay deuda, así que tampoco hace falta saber a quién se
    # le compró: el cheque puede cargarse sin cliente, como siempre.
    payload = _create(usd="4200", cotiz="1555", con_vendedor=False)
    assert payload.usd_entregados == Decimal("4200")


# ══════════════════════════════════════════════════════════════════════
#  El bot: un pago dicho una vez para varios cheques
# ══════════════════════════════════════════════════════════════════════

def test_los_dolares_de_un_fajo_se_reparten_no_se_copian() -> None:
    # "Le di 1000 dólares a 1000 por estos dos" es UN pago: copiarlo a cada
    # cheque sacaría 2000 del cajón, el doble de los billetes que salieron.
    from app.services.whatsapp.dispatcher import _repartir_usd

    data = {"usd_entregados": 1000, "cotizacion_usd": 1000}
    items = [
        {"monto": 1000000, "porcentaje_compra": 40},  # neto 600.000
        {"monto": 1000000, "porcentaje_compra": 40},  # neto 600.000
    ]
    sobran = _repartir_usd(data, items)

    assert items[0]["usd_entregados"] == Decimal("600.00")
    assert items[1]["usd_entregados"] == Decimal("400.00")
    assert sobran == Decimal("0.00")


def test_el_reparto_no_deja_a_ningun_cheque_pagado_de_mas() -> None:
    # Los dólares de cada cheque se redondean para abajo: si la cuenta no da
    # redonda, el centavo que falta se paga en pesos. Al revés —redondeando
    # arriba— el alta rechazaría el cheque por pagado de más.
    from app.services.whatsapp.dispatcher import _repartir_usd

    data = {"usd_entregados": 1000, "cotizacion_usd": 1555}
    items = [
        {"monto": 1000000, "porcentaje_compra": 10},  # neto 900.000
        {"monto": 1000000, "porcentaje_compra": 10},  # neto 900.000
    ]
    _repartir_usd(data, items)

    # 900.000 / 1555 no da redondo: al primero le tocan 578,77 USD ($899.987,35)
    # y no 578,78 ($900.002,90), que el alta rechazaría por pagado de más.
    assert items[0]["usd_entregados"] == Decimal("578.77")
    for item in items:
        assert item["usd_entregados"] * Decimal("1555") <= Decimal("900000")


def test_dolares_que_sobran_para_todo_el_fajo() -> None:
    # Alcanzan para más que todos los cheques juntos: es un dedazo, y el alta no
    # carga ninguno (mismo criterio que el sobrante en pesos).
    from app.services.whatsapp.dispatcher import _repartir_usd

    data = {"usd_entregados": 1000, "cotizacion_usd": 1000}
    items = [
        {"monto": 500000, "porcentaje_compra": 0},
        {"monto": 100000, "porcentaje_compra": 0},
    ]
    assert _repartir_usd(data, items) == Decimal("400.00")


def test_los_pesos_del_fajo_cubren_lo_que_los_dolares_no() -> None:
    # El reparto en pesos corre DESPUÉS del de dólares y sobre lo que queda: si
    # tomara cada cheque por su neto entero, el primero se comería todo y el
    # sobrante daría de más.
    from app.services.whatsapp.dispatcher import _repartir_abonado, _repartir_usd

    data = {
        "usd_entregados": 500, "cotizacion_usd": 1000,  # cubren 500.000
        "monto_abonado": 400000,
    }
    items = [
        {"monto": 1000000, "porcentaje_compra": 50},  # neto 500.000
        {"monto": 1000000, "porcentaje_compra": 60},  # neto 400.000
    ]
    _repartir_usd(data, items)
    sobrante = _repartir_abonado(data, items)

    # Los dólares pagaron el primero entero; los pesos, el segundo.
    assert items[0]["usd_entregados"] == Decimal("500.00")
    assert items[0]["monto_abonado"] == Decimal("0.00")
    assert items[1]["monto_abonado"] == Decimal("400000.00")
    assert sobrante == Decimal("0.00")


# ══════════════════════════════════════════════════════════════════════
#  El prompt le pide la cotización al operador, no la inventa
# ══════════════════════════════════════════════════════════════════════

def test_el_prompt_conoce_el_pago_en_dolares() -> None:
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert "usd_entregados" in _SYSTEM_PROMPT
    assert "cotizacion_usd" in _SYSTEM_PROMPT


def test_el_prompt_prohibe_inventar_la_cotizacion_del_cheque() -> None:
    # Sin cotización el sistema no sabe cuánto del cheque quedó pagado: el bot
    # pregunta en vez de completar con el blue.
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert "LA COTIZACIÓN NO SE ASUME NUNCA" in _SYSTEM_PROMPT
