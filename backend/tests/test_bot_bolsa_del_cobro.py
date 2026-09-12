"""Contra cuál de las dos bolsas de deuda imputa el bot un pago suelto (§2.c).

Un cliente puede deberle al negocio por su **cuenta** —cheques fiados y deudas
libres, que se cobran juntas de lo más viejo a lo más nuevo— y por un
**préstamo**, que se cobra aparte. "Kiosco me entregó 200 lucas" no dice cuál de
las dos, y elegir mal no se ve: la plata baja un saldo que el operador no estaba
mirando y el que sí miraba sigue igual.

La regla del dueño (2026-09-12): adentro de una bolsa el sistema reparte solo,
entre las dos **pregunta siempre**, salvo que el operador lo haya aclarado en el
mensaje ("del préstamo") o que el cliente deba de un solo lado.

Unitarios puros: no llaman al modelo. La BD es un stand-in que contesta por
entidad, así que si `_bolsa_y_moneda` dejara de mirar una de las dos bolsas el
test lo ve.
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
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    Moneda,
    Prestamo,
    PrestamoEstado,
)
from app.services.ia.claude import _SYSTEM_PROMPT
from app.services.whatsapp.dispatcher import _Repreguntar, _bolsa_y_moneda

CLIENTE_ID = uuid.uuid4()


class DB:
    """Sesión mínima: contesta por tabla y resuelve el cliente."""

    def __init__(
        self,
        fiados: list[Fiado] | None = None,
        deudas: list[DeudaSimple] | None = None,
        prestamos: list[Prestamo] | None = None,
    ) -> None:
        self._por_entidad = {
            Fiado: fiados or [],
            DeudaSimple: deudas or [],
            Prestamo: prestamos or [],
        }

    def scalars(self, stmt):  # noqa: ANN001, ANN202
        return iter(self._por_entidad.get(stmt.column_descriptions[0]["entity"], []))

    def get(self, _modelo, _id):  # noqa: ANN001, ANN202
        return _cliente()


def _cliente() -> Cliente:
    return Cliente(id=CLIENTE_ID, nombre="Kiosco")


def _fiado(saldo: str) -> Fiado:
    return Fiado(
        id=uuid.uuid4(),
        cheque_id=uuid.uuid4(),
        cliente_id=CLIENTE_ID,
        monto_original=Decimal("100000.00"),
        porcentaje_venta=Decimal("10"),
        saldo_pendiente=Decimal(saldo),
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=date(2026, 3, 10),
    )


def _deuda(saldo: str, moneda: Moneda = Moneda.ARS) -> DeudaSimple:
    return DeudaSimple(
        id=uuid.uuid4(),
        cliente_id=CLIENTE_ID,
        concepto="Mercadería",
        monto=Decimal(saldo),
        saldo_pendiente=Decimal(saldo),
        moneda=moneda,
        estado=DeudaSimpleEstado.ABIERTA,
        fecha=date(2026, 1, 5),
    )


def _prestamo(saldo: str, moneda: Moneda = Moneda.ARS) -> Prestamo:
    p = Prestamo(
        id=uuid.uuid4(),
        cliente_id=CLIENTE_ID,
        credito=Decimal(saldo),
        moneda=moneda,
        cuotas=1,
        total_a_cobrar=Decimal(saldo),
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 2, 1),
    )
    p.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=p.id,
            numero_cuota=1,
            fecha_vencimiento=date(2026, 3, 1),
            monto=Decimal(saldo),
            monto_pagado=Decimal("0.00"),
            estado=CuotaEstado.PENDIENTE,
        )
    ]
    return p


# ── Cuando no hay nada que elegir, no molesta al operador ─────────────


def test_si_solo_debe_en_cuenta_va_a_la_cuenta() -> None:
    db = DB(fiados=[_fiado("50000")], deudas=[_deuda("30000")])

    moneda, destino, en_cuenta, en_credito = _bolsa_y_moneda(db, _cliente(), {}, "el pago")

    assert (moneda, destino) == (Moneda.ARS, "CUENTA")
    assert en_cuenta == Decimal("80000.00")
    assert en_credito == Decimal("0.00")


def test_si_solo_debe_un_prestamo_va_al_prestamo() -> None:
    """El caso que se había roto: "Pedrón me entregó 200 lucas" cuando lo único
    que debe es un crédito. Antes contestaba que no debía nada."""
    db = DB(prestamos=[_prestamo("600000")])

    moneda, destino, en_cuenta, en_credito = _bolsa_y_moneda(db, _cliente(), {}, "el pago")

    assert (moneda, destino) == (Moneda.ARS, "PRESTAMO")
    assert en_cuenta == Decimal("0.00")
    assert en_credito == Decimal("600000.00")


# ── Cuando hay que elegir, pregunta ───────────────────────────────────


def test_si_debe_por_los_dos_lados_pregunta() -> None:
    """Decisión del dueño: acá no puede haber un default. La pregunta tiene que
    mostrar los dos números, que es lo que le permite al operador contestar."""
    db = DB(fiados=[_fiado("50000")], prestamos=[_prestamo("600000")])

    with pytest.raises(_Repreguntar) as falta:
        _bolsa_y_moneda(db, _cliente(), {}, "lo que te entregó")

    mensaje = falta.value.mensaje
    assert "cuenta" in mensaje and "préstamo" in mensaje
    assert "50.000" in mensaje and "600.000" in mensaje


def test_el_fiado_y_la_deuda_libre_nunca_se_preguntan() -> None:
    """Entre esas dos no hay decisión que tomar: es una sola bolsa y se reparte
    de lo más viejo a lo más nuevo, como siempre."""
    db = DB(fiados=[_fiado("50000")], deudas=[_deuda("30000")])

    _, destino, _, _ = _bolsa_y_moneda(db, _cliente(), {}, "el pago")

    assert destino == "CUENTA"


def test_el_operador_puede_decirlo_y_entonces_no_pregunta() -> None:
    db = DB(fiados=[_fiado("50000")], prestamos=[_prestamo("600000")])

    _, destino, _, _ = _bolsa_y_moneda(db, _cliente(), {"destino": "PRESTAMO"}, "el pago")

    assert destino == "PRESTAMO"


def test_pedir_una_bolsa_vacia_se_avisa_no_se_desvia() -> None:
    """"Cobrale del préstamo" a alguien que no tiene préstamo no puede caer en
    la cuenta por descarte: sería cobrar otra cosa que la que dijo el operador."""
    db = DB(fiados=[_fiado("50000")])

    with pytest.raises(_Repreguntar) as falta:
        _bolsa_y_moneda(db, _cliente(), {"destino": "PRESTAMO"}, "el pago")

    assert "no tiene préstamos abiertos" in falta.value.mensaje


# ── La moneda se resuelve antes que la bolsa ──────────────────────────


def test_si_debe_en_las_dos_monedas_pregunta_la_moneda_primero() -> None:
    db = DB(deudas=[_deuda("30000"), _deuda("120", Moneda.USD)])

    with pytest.raises(_Repreguntar) as falta:
        _bolsa_y_moneda(db, _cliente(), {}, "el pago")

    assert "pesos" in falta.value.mensaje and "dólares" in falta.value.mensaje


def test_la_moneda_elegida_acota_las_dos_bolsas() -> None:
    """Debe cuenta en pesos y préstamo en dólares: una vez elegida la moneda ya
    no hay dos bolsas que desambiguar."""
    db = DB(deudas=[_deuda("30000")], prestamos=[_prestamo("1000", Moneda.USD)])

    moneda, destino, _, _ = _bolsa_y_moneda(
        db, _cliente(), {"moneda_deuda": "USD"}, "el pago"
    )

    assert (moneda, destino) == (Moneda.USD, "PRESTAMO")


def test_el_que_no_debe_nada_no_dispara_ninguna_pregunta() -> None:
    with pytest.raises(_Repreguntar) as falta:
        _bolsa_y_moneda(DB(), _cliente(), {}, "el pago")

    assert "no tiene deuda abierta" in falta.value.mensaje


# ── El prompt tiene que saber mandar el dato ──────────────────────────


def test_el_prompt_documenta_el_destino() -> None:
    """Sin esto el modelo nunca manda `destino` y el bot pregunta siempre, aun
    cuando el operador ya lo dijo en la frase."""
    seccion = _SYSTEM_PROMPT.split("9b. COBRAR_DEUDA_CLIENTE")[1].split(
        "10. REGISTRAR_DEUDA"
    )[0]

    assert "destino" in seccion
    assert "PRESTAMO" in seccion and "CUENTA" in seccion
    # Y que sepa contestar la repregunta rearmando el intent.
    assert "rearmá" in seccion
