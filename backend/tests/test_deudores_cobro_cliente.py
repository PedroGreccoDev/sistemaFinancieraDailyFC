"""Cobro consolidado de la deuda de un cliente (pestaña General).

Lo que se custodia acá es la parte que no vive en ningún módulo: que las tres
fuentes de deuda de un cliente —cheques fiados, deudas libres y préstamos— se
ordenen en una sola cuota común por fecha de origen, y que un importe imputado
sobre esa cuota caiga en el módulo correcto con la línea de caja que le
corresponde. El reparto en sí (`repartir_cobro_fifo`) y el vuelto de un cheque
(`calcular_imputacion_y_vuelto`) se cubren en `test_deudas_simples.py`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

from app.db.models import (
    CajaCategoria,
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
from app.services.deudas_simples import repartir_cobro_fifo
from app.services.deudores import (
    _imputar,
    armar_renglones,
    saldo_prestamo,
)


class FakeDB:
    """Sesión mínima: junta lo que se le agrega, como hace `caja.registrar`."""

    def __init__(self) -> None:
        self.agregados: list[object] = []

    def add(self, obj: object) -> None:
        self.agregados.append(obj)


def _fiado(saldo: str, fecha: date, creado: datetime | None = None) -> Fiado:
    return Fiado(
        id=uuid.uuid4(),
        cheque_id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        monto_original=Decimal("100000.00"),
        porcentaje_venta=Decimal("10"),
        saldo_pendiente=Decimal(saldo),
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=fecha,
        created_at=creado,
    )


def _deuda(saldo: str, fecha: date, moneda: Moneda = Moneda.ARS) -> DeudaSimple:
    return DeudaSimple(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        concepto="Mercadería",
        monto=Decimal(saldo),
        saldo_pendiente=Decimal(saldo),
        moneda=moneda,
        estado=DeudaSimpleEstado.ABIERTA,
        fecha=fecha,
    )


def _prestamo(
    cuotas: list[str],
    fecha: date,
    moneda: Moneda = Moneda.ARS,
    pagado: list[str] | None = None,
    cobradas: int = 0,
) -> Prestamo:
    """Préstamo con `cuotas` montos; las primeras `cobradas` ya están COBRADAS."""
    total = sum((Decimal(c) for c in cuotas), Decimal("0.00"))
    prestamo = Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        credito=total,
        moneda=moneda,
        cuotas=len(cuotas),
        total_a_cobrar=total,
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=fecha,
    )
    prestamo.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=prestamo.id,
            numero_cuota=i + 1,
            fecha_vencimiento=fecha,
            monto=Decimal(monto),
            monto_pagado=Decimal(pagado[i]) if pagado else Decimal("0.00"),
            estado=CuotaEstado.COBRADA if i < cobradas else CuotaEstado.PENDIENTE,
        )
        for i, monto in enumerate(cuotas)
    ]
    return prestamo


# ── El orden de la cuota común ────────────────────────────────────────


def test_orden_por_fecha_de_origen_cruzando_tipos() -> None:
    # Tres deudas de tipos distintos: se ordenan por la fecha en que se
    # originaron, sin que el tipo tenga nada que ver.
    fiado = _fiado("50000", date(2026, 3, 10))
    deuda = _deuda("30000", date(2026, 1, 5))
    prestamo = _prestamo(["20000", "20000"], date(2026, 2, 1))

    renglones = armar_renglones([fiado], [deuda], [prestamo], Moneda.ARS)

    assert [r.tipo for r in renglones] == ["deuda_simple", "prestamo", "fiado"]


def test_mismo_dia_desempata_por_created_at() -> None:
    # Dos fiados del mismo día: primero el que se cargó antes.
    tarde = _fiado("10000", date(2026, 5, 1), datetime(2026, 5, 1, 18, tzinfo=timezone.utc))
    temprano = _fiado("20000", date(2026, 5, 1), datetime(2026, 5, 1, 9, tzinfo=timezone.utc))

    renglones = armar_renglones([tarde, temprano], [], [], Moneda.ARS)

    assert [r.saldo for r in renglones] == [Decimal("20000"), Decimal("10000")]


def test_los_fiados_no_entran_en_un_cobro_en_dolares() -> None:
    # Los cheques (y por ende los fiados) son siempre en pesos: en USD solo
    # entran deudas libres y préstamos en dólares. Sumarlos mezclaría cajas.
    fiado = _fiado("50000", date(2026, 1, 1))
    deuda_usd = _deuda("300", date(2026, 2, 1), Moneda.USD)
    deuda_ars = _deuda("40000", date(2026, 1, 15))
    prestamo_usd = _prestamo(["100", "100"], date(2026, 3, 1), Moneda.USD)

    renglones = armar_renglones(
        [fiado], [deuda_usd, deuda_ars], [prestamo_usd], Moneda.USD
    )

    assert [r.tipo for r in renglones] == ["deuda_simple", "prestamo"]
    assert sum((r.saldo for r in renglones), Decimal("0.00")) == Decimal("500.00")


def test_las_operaciones_sin_saldo_quedan_afuera() -> None:
    # Un préstamo con todas las cuotas cobradas no es deuda, aunque siga
    # figurando ACTIVO hasta que se refresque su estado.
    saldado = _prestamo(["10000"], date(2026, 1, 1), cobradas=1)
    vivo = _prestamo(["10000", "10000"], date(2026, 2, 1), cobradas=1)

    renglones = armar_renglones([], [], [saldado, vivo], Moneda.ARS)

    assert len(renglones) == 1
    assert renglones[0].saldo == Decimal("10000.00")


def test_saldo_de_prestamo_descuenta_los_pagos_parciales() -> None:
    # Cuota 1 de 10.000 con 4.000 pagados + cuota 2 entera → faltan 16.000.
    prestamo = _prestamo(["10000", "10000"], date(2026, 1, 1), pagado=["4000", "0"])
    assert saldo_prestamo(prestamo) == Decimal("16000.00")


# ── La imputación cae en el módulo correcto ───────────────────────────


def test_un_cobro_llena_la_deuda_mas_vieja_y_derrama_en_la_siguiente() -> None:
    # El cliente debe 30.000 de un fiado (más viejo) y 50.000 de un préstamo, y
    # entrega 40.000: cancela el fiado y deja 40.000 del préstamo.
    fiado = _fiado("30000", date(2026, 1, 10))
    prestamo = _prestamo(["25000", "25000"], date(2026, 2, 10))
    renglones = armar_renglones([fiado], [], [prestamo], Moneda.ARS)

    reparto = repartir_cobro_fifo(
        [r.saldo for r in renglones], Decimal("40000.00"), Decimal("40000.00")
    )

    db = FakeDB()
    resultados = [
        _imputar(
            db,
            renglon,
            cliente_nombre="Kiosco",
            imputado=imputa,
            fecha=date(2026, 6, 1),
            monto_caja=plata,
            moneda_pago=Moneda.ARS,
            cotizacion=None,
        )
        for renglon, (imputa, plata) in zip(renglones, reparto)
        if imputa > Decimal("0.00")
    ]

    assert [r.tipo for r in resultados] == ["fiado", "prestamo"]
    assert resultados[0].cancelado is True
    assert resultados[0].saldo_restante == Decimal("0.00")
    assert resultados[1].imputado == Decimal("10000.00")
    assert resultados[1].saldo_restante == Decimal("40000.00")
    assert fiado.estado == FiadoEstado.CANCELADO
    # Dentro del préstamo el importe cae en la cuota más vieja: 10.000 contra
    # una cuota de 25.000 la deja paga a medias, sin tocar la siguiente.
    assert prestamo.cuotas_detalle[0].monto_pagado == Decimal("10000.00")
    assert prestamo.cuotas_detalle[0].estado == CuotaEstado.PENDIENTE
    assert prestamo.cuotas_detalle[1].monto_pagado == Decimal("0.00")


def test_cada_operacion_asienta_su_propia_linea_de_caja() -> None:
    # No hay una línea única "cobro al cliente": anular una de las operaciones
    # borra sus líneas por referencia, y una línea compartida se llevaría puesta
    # plata de las otras.
    fiado = _fiado("30000", date(2026, 1, 10))
    deuda = _deuda("20000", date(2026, 2, 10))
    renglones = armar_renglones([fiado], [deuda], [], Moneda.ARS)

    db = FakeDB()
    for renglon, imputa in zip(renglones, [Decimal("30000.00"), Decimal("20000.00")]):
        _imputar(
            db,
            renglon,
            cliente_nombre="Kiosco",
            imputado=imputa,
            fecha=date(2026, 6, 1),
            monto_caja=imputa,
            moneda_pago=Moneda.ARS,
            cotizacion=None,
        )

    lineas = db.agregados
    assert len(lineas) == 2
    assert [l.categoria for l in lineas] == [
        CajaCategoria.COBRO_FIADO,
        CajaCategoria.COBRO_DEUDA,
    ]
    assert [l.referencia_tipo for l in lineas] == ["fiado", "deuda_simple_cobro"]
    assert sum((l.monto for l in lineas), Decimal("0.00")) == Decimal("50000.00")


def test_el_cobro_con_cheque_no_mueve_la_caja() -> None:
    # El cheque entra a cartera: la plata se reconoce al venderlo o cobrarlo.
    # Los saldos sí bajan.
    fiado = _fiado("30000", date(2026, 1, 10))
    renglones = armar_renglones([fiado], [], [], Moneda.ARS)

    db = FakeDB()
    resultado = _imputar(
        db,
        renglones[0],
        cliente_nombre="Kiosco",
        imputado=Decimal("30000.00"),
        fecha=date(2026, 6, 1),
        monto_caja=None,
        moneda_pago=Moneda.ARS,
        cotizacion=None,
    )

    assert db.agregados == []
    assert resultado.cancelado is True
    assert fiado.saldo_pendiente == Decimal("0.00")


# ── El intent del bot ─────────────────────────────────────────────────


def test_cobrar_deuda_cliente_es_un_intent_valido() -> None:
    """Si el intent no está en la lista blanca, el parser lo descarta a
    DESCONOCIDO y el bot responde "no entendí" en vez de cobrar."""
    from app.services.ia.claude import INTENTS

    assert "COBRAR_DEUDA_CLIENTE" in INTENTS


def test_el_prompt_hace_del_cobro_general_el_default() -> None:
    """"X me pagó 50 lucas" es la cuenta corriente del cliente, no una cuota.

    Antes ese mensaje caía en COBRAR_CUOTA por descarte, que imputa contra un
    préstamo aunque lo más viejo que deba sea un fiado. Los dos cobros puntuales
    quedan para cuando el operador dice contra qué va la plata."""
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert "COBRAR_DEUDA_CLIENTE" in _SYSTEM_PROMPT
    seccion = _SYSTEM_PROMPT.split("9b. COBRAR_DEUDA_CLIENTE")[1].split("10. REGISTRAR_DEUDA")[0]
    # El bloque tiene que contrastar los tres cobros, no solo describir el nuevo.
    assert "COBRAR_CUOTA" in seccion
    assert "COBRAR_FIADO_EFECTIVO" in seccion
    # Y la regla de ambigüedad tiene que apuntar al general, no a la cuota.
    regla = _SYSTEM_PROMPT.split("11. Ambigüedad")[1].split("12.")[0]
    assert "COBRAR_DEUDA_CLIENTE" in regla


def test_el_prompt_pide_el_monto_en_vez_de_asumir_la_cuota_entera() -> None:
    """"Juan pagó" sin importe se pregunta, no se cobra _(decisión del dueño)_.

    Dar por cobrada una cuota entera cuando el cliente entregó menos asienta en
    la caja del día plata que no entró. El operador dice cuánto le dieron o no
    hay cobro."""
    from app.services.ia.claude import _SYSTEM_PROMPT

    seccion = _SYSTEM_PROMPT.split("9b. COBRAR_DEUDA_CLIENTE")[1].split("10. REGISTRAR_DEUDA")[0]
    assert "SIN IMPORTE NO SE COBRA" in seccion
    assert "ACLARACION_REQUERIDA" in seccion
    regla = _SYSTEM_PROMPT.split("11. Ambigüedad")[1].split("12.")[0]
    assert "ACLARACION_REQUERIDA" in regla


def test_el_dispatcher_registra_el_intent() -> None:
    """El intent tiene que estar cableado al handler, no solo documentado."""
    import inspect

    from app.services.whatsapp import dispatcher

    fuente = inspect.getsource(dispatcher.dispatch)
    assert 'intent == "COBRAR_DEUDA_CLIENTE"' in fuente
    assert hasattr(dispatcher, "_cobrar_deuda_cliente")


def test_el_prompt_separa_me_debe_de_me_entrego() -> None:
    """"Kiosco me debe 200 lucas" y "Kiosco me entregó 200 lucas" mueven la caja
    al revés: la primera es un EGRESO (le diste la plata) y la segunda un INGRESO
    (te la trajo). Mismo cliente, mismo monto, error invisible — y la caja del día
    queda errada por el doble."""
    from app.services.ia.claude import _SYSTEM_PROMPT

    assert '"ME DEBE" NO ES "ME ENTREGÓ"' in _SYSTEM_PROMPT
    bloque = _SYSTEM_PROMPT.split('"ME DEBE" NO ES "ME ENTREGÓ"')[1].split("11. MOVIMIENTO_EFECTIVO")[0]
    assert "REGISTRAR_DEUDA_CLIENTE" in bloque
    assert "COBRAR_DEUDA_CLIENTE" in bloque
