"""Préstamo a interés fijo: los ciclos de 30 días, la mora y la cancelación.

Lo que se prueba acá es la aritmética del calendario y las reglas de negocio que
no dependen de la BD. Son las que más caro salen si están mal, porque el error no
se ve: un período de más o de menos cambia cuánto debe el cliente y nadie lo nota
hasta que no cierra la cuenta.

Las tres reglas del dueño que fijan todo lo demás:
  - **Sin prorrateo**: el interés se debe al ENTRAR al período, no al cumplirlo.
  - **La mora se acumula**: el interés nuevo no reemplaza al viejo, se suma.
  - **El capital no está en las cuotas**: se liquida al cancelar, y mientras haya
    capital afuera el préstamo sigue vivo aunque no deba un peso de interés.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import (
    Cuota,
    CuotaEstado,
    FrecuenciaCuotas,
    Moneda,
    Prestamo,
    PrestamoEstado,
    PrestamoTipo,
)
from app.services import prestamos as svc
from app.services.deudores import _detalle_prestamo, saldo_prestamo


class FakeDB:
    """Sesión mínima: junta lo que se le agrega. `devengar_periodos` no hace más."""

    def __init__(self) -> None:
        self.agregados: list[object] = []

    def add(self, obj: object) -> None:
        self.agregados.append(obj)


def _prestamo(
    *,
    credito: str = "5000000",
    interes: str = "500000",
    dia_cobro: date = date(2026, 3, 10),
    capital_pendiente: str | None = None,
    moneda: Moneda = Moneda.ARS,
) -> Prestamo:
    """Un préstamo a interés fijo recién dado de alta, sin períodos devengados."""
    return Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        tipo_prestamo=PrestamoTipo.INTERES_FIJO,
        credito=Decimal(credito),
        moneda=moneda,
        cuotas=0,
        frecuencia=FrecuenciaCuotas.CADA_30_DIAS,
        total_a_cobrar=Decimal(credito),
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 2, 8),
        monto_interes_fijo=Decimal(interes),
        dia_cobro=dia_cobro,
        capital_pendiente=Decimal(capital_pendiente if capital_pendiente is not None else credito),
        cuotas_detalle=[],
    )


def _devengar(prestamo: Prestamo, hasta: date) -> bool:
    return svc.devengar_periodos(FakeDB(), prestamo, hasta)


# ── El calendario de ciclos ──────────────────────────────────────────────────

def test_el_primer_periodo_arranca_el_dia_de_cobro() -> None:
    assert svc.fecha_de_periodo(date(2026, 3, 10), 1) == date(2026, 3, 10)


def test_cada_periodo_cae_30_dias_despues_del_anterior() -> None:
    # 30 días exactos, no "el mismo día del mes que viene": marzo tiene 31.
    assert svc.fecha_de_periodo(date(2026, 3, 10), 2) == date(2026, 4, 9)
    assert svc.fecha_de_periodo(date(2026, 3, 10), 3) == date(2026, 5, 9)


def test_antes_del_dia_de_cobro_no_hay_ningun_periodo() -> None:
    assert svc.periodos_cumplidos(date(2026, 3, 10), date(2026, 3, 9)) == 0


def test_el_dia_de_cobro_ya_cuenta_como_periodo_cumplido() -> None:
    # Sin prorrateo: al ENTRAR al período el interés ya se debe entero.
    assert svc.periodos_cumplidos(date(2026, 3, 10), date(2026, 3, 10)) == 1


def test_el_ultimo_dia_del_ciclo_sigue_siendo_el_mismo_periodo() -> None:
    assert svc.periodos_cumplidos(date(2026, 3, 10), date(2026, 4, 8)) == 1


def test_el_dia_29_no_abre_periodo_y_el_30_si() -> None:
    assert svc.periodos_cumplidos(date(2026, 3, 10), date(2026, 4, 8)) == 1
    assert svc.periodos_cumplidos(date(2026, 3, 10), date(2026, 4, 9)) == 2


def test_la_frecuencia_de_30_dias_no_es_mensual() -> None:
    # `calcular_vencimiento` con MENSUAL cae el 10 de abril; con CADA_30_DIAS, el 9.
    inicio = date(2026, 3, 10)
    assert svc.calcular_vencimiento(inicio, FrecuenciaCuotas.MENSUAL, 1) == date(2026, 4, 10)
    assert svc.calcular_vencimiento(inicio, FrecuenciaCuotas.CADA_30_DIAS, 1) == date(2026, 4, 9)


# ── Devengo: los períodos nacen de a uno ─────────────────────────────────────

def test_no_devenga_nada_antes_del_primer_cobro() -> None:
    p = _prestamo()
    assert _devengar(p, date(2026, 3, 9)) is False
    assert p.cuotas_detalle == []
    # El total todavía es el capital: no hay interés que sumar.
    assert p.total_a_cobrar == Decimal("5000000")
    assert p.ganancia == Decimal("0.00")


def test_el_primer_periodo_nace_el_dia_de_cobro() -> None:
    p = _prestamo()
    assert _devengar(p, date(2026, 3, 10)) is True
    assert [c.numero_cuota for c in p.cuotas_detalle] == [1]
    assert p.cuotas_detalle[0].monto == Decimal("500000")
    assert p.cuotas_detalle[0].fecha_vencimiento == date(2026, 3, 10)


def test_el_devengo_suma_al_total_y_a_la_ganancia() -> None:
    """El total de un préstamo a interés fijo no se conoce al alta: se va
    conociendo. Cada interés que nace es ganancia devengada."""
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))  # tres períodos
    assert len(p.cuotas_detalle) == 3
    assert p.total_a_cobrar == Decimal("6500000")  # 5.000.000 + 3 × 500.000
    assert p.ganancia == Decimal("1500000")


def test_devengar_dos_veces_el_mismo_dia_no_duplica_nada() -> None:
    """Lo cuelgan todas las lecturas: si no fuera idempotente, mirar el panel
    dos veces le cobraría al cliente dos veces el mismo interés."""
    p = _prestamo()
    _devengar(p, date(2026, 4, 9))
    assert _devengar(p, date(2026, 4, 9)) is False
    assert len(p.cuotas_detalle) == 2
    assert p.total_a_cobrar == Decimal("6000000")


def test_un_prestamo_normal_nunca_devenga() -> None:
    normal = Prestamo(
        id=uuid.uuid4(), cliente_id=uuid.uuid4(), tipo_prestamo=PrestamoTipo.NORMAL,
        credito=Decimal("100000"), moneda=Moneda.ARS, cuotas=2,
        frecuencia=FrecuenciaCuotas.MENSUAL, total_a_cobrar=Decimal("120000"),
        ganancia=Decimal("20000"), estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 1, 1), cuotas_detalle=[],
    )
    assert _devengar(normal, date(2027, 1, 1)) is False
    assert normal.cuotas_detalle == []


def test_con_el_capital_saldado_no_nacen_periodos_nuevos() -> None:
    """El interés se cobra por tener el capital afuera. Devuelto el capital, no
    hay por qué seguir devengando."""
    p = _prestamo(capital_pendiente="0")
    assert _devengar(p, date(2026, 6, 8)) is False
    assert p.cuotas_detalle == []


# ── Mora: se acumula, no reemplaza ───────────────────────────────────────────

def test_el_periodo_vigente_es_el_ultimo_devengado() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))
    assert svc.periodo_vigente(p).numero_cuota == 3


def test_los_periodos_viejos_impagos_quedan_en_mora() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))
    estados = [c.estado for c in svc.periodos(p)]
    assert estados == [CuotaEstado.EN_MORA, CuotaEstado.EN_MORA, CuotaEstado.PENDIENTE]


def test_la_mora_suma_los_periodos_viejos_y_no_el_vigente() -> None:
    """La regla del dueño: el interés nuevo NO reemplaza al que quedó impago."""
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))
    assert svc.mora_acumulada(p) == Decimal("1000000")  # los dos primeros
    assert svc.saldo_cuota(svc.periodo_vigente(p)) == Decimal("500000")


def test_un_periodo_cobrado_sale_de_la_mora() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))
    viejo = svc.periodos(p)[0]
    viejo.monto_pagado = viejo.monto
    viejo.estado = CuotaEstado.COBRADA
    assert svc.mora_acumulada(p) == Decimal("500000")


def test_un_pago_parcial_deja_solo_el_resto_en_mora() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 4, 9))
    viejo = svc.periodos(p)[0]
    viejo.monto_pagado = Decimal("200000")
    assert svc.mora_acumulada(p) == Decimal("300000")


def test_al_devengar_uno_nuevo_el_vigente_anterior_pasa_a_mora() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 3, 10))
    assert svc.periodos(p)[0].estado == CuotaEstado.PENDIENTE
    _devengar(p, date(2026, 4, 9))
    assert svc.periodos(p)[0].estado == CuotaEstado.EN_MORA


# ── Cancelación ──────────────────────────────────────────────────────────────

def test_cancelar_es_capital_mas_el_interes_del_periodo_vigente() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 3, 10))
    assert svc.total_cancelacion(p, incluir_mora=False) == Decimal("5500000")


def test_el_interes_del_periodo_en_curso_va_completo_aunque_falten_dias() -> None:
    """Sin prorrateo: cancelar el día 2 de un ciclo de 30 paga el interés entero."""
    p = _prestamo()
    _devengar(p, date(2026, 4, 11))  # dos días dentro del segundo período
    assert svc.saldo_cuota(svc.periodo_vigente(p)) == Decimal("500000")


def test_la_mora_entra_en_la_cancelacion_solo_si_se_pide() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 5, 9))
    assert svc.total_cancelacion(p, incluir_mora=False) == Decimal("5500000")
    assert svc.total_cancelacion(p, incluir_mora=True) == Decimal("6500000")


def test_cancelar_con_capital_ya_devuelto_solo_cobra_el_interes() -> None:
    p = _prestamo(capital_pendiente="0")
    p.cuotas_detalle = [
        Cuota(id=uuid.uuid4(), prestamo=p, numero_cuota=1,
              fecha_vencimiento=date(2026, 3, 10), monto=Decimal("500000"),
              monto_pagado=Decimal("0.00"), estado=CuotaEstado.PENDIENTE)
    ]
    assert svc.total_cancelacion(p, incluir_mora=True) == Decimal("500000")


# ── Estado del préstamo ──────────────────────────────────────────────────────

def test_saldar_todo_el_interes_no_cancela_el_prestamo_si_queda_capital() -> None:
    """La trampa central de la modalidad. Las cuotas son interés: darlo por
    cancelado porque no quedan cuotas impagas borraría del panel millones de
    capital que siguen prestados."""
    p = _prestamo()
    _devengar(p, date(2026, 3, 10))
    for c in p.cuotas_detalle:
        c.monto_pagado = c.monto
        c.estado = CuotaEstado.COBRADA
    svc.recalcular_estado(p)
    assert p.estado == PrestamoEstado.ACTIVO


def test_con_capital_e_interes_saldados_el_prestamo_queda_cancelado() -> None:
    p = _prestamo(capital_pendiente="0")
    svc.recalcular_estado(p)
    assert p.estado == PrestamoEstado.CANCELADO


def test_capital_saldado_con_mora_pendiente_mantiene_el_prestamo_vivo() -> None:
    """El operador puede cancelar y cobrar la mora aparte. Esa deuda tiene que
    seguir viéndose en la cuenta del cliente."""
    p = _prestamo(capital_pendiente="0")
    p.cuotas_detalle = [
        Cuota(id=uuid.uuid4(), prestamo=p, numero_cuota=1,
              fecha_vencimiento=date(2026, 3, 10), monto=Decimal("500000"),
              monto_pagado=Decimal("0.00"), estado=CuotaEstado.EN_MORA)
    ]
    svc.recalcular_estado(p)
    assert p.estado == PrestamoEstado.ACTIVO


def test_un_prestamo_normal_se_cancela_al_saldar_la_ultima_cuota() -> None:
    normal = Prestamo(
        id=uuid.uuid4(), cliente_id=uuid.uuid4(), tipo_prestamo=PrestamoTipo.NORMAL,
        credito=Decimal("100000"), moneda=Moneda.ARS, cuotas=1,
        frecuencia=FrecuenciaCuotas.MENSUAL, total_a_cobrar=Decimal("120000"),
        ganancia=Decimal("20000"), estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 1, 1), cuotas_detalle=[],
    )
    normal.cuotas_detalle = [
        Cuota(id=uuid.uuid4(), prestamo=normal, numero_cuota=1,
              fecha_vencimiento=date(2026, 2, 1), monto=Decimal("120000"),
              monto_pagado=Decimal("120000"), estado=CuotaEstado.COBRADA)
    ]
    svc.recalcular_estado(normal)
    assert normal.estado == PrestamoEstado.CANCELADO


# ── Próxima fecha de cobro ───────────────────────────────────────────────────

def test_sin_periodos_la_proxima_fecha_es_el_dia_de_cobro() -> None:
    assert svc.proxima_fecha_cobro(_prestamo()) == date(2026, 3, 10)


def test_con_dos_periodos_la_proxima_es_30_dias_despues_del_segundo() -> None:
    p = _prestamo()
    _devengar(p, date(2026, 4, 9))
    assert svc.proxima_fecha_cobro(p) == date(2026, 5, 9)


# ── Cómo entra en la cuenta consolidada del cliente ──────────────────────────

def test_el_cobro_a_cuenta_del_cliente_baja_interes_y_nunca_capital() -> None:
    """"Kiosco me entregó 200 lucas" imputa a lo que se debe mes a mes. El
    capital vuelve con un acto explícito, no con un cobro genérico."""
    p = _prestamo()
    _devengar(p, date(2026, 4, 9))
    assert saldo_prestamo(p) == Decimal("1000000")  # dos períodos, sin el capital


def test_el_renglon_del_cliente_no_habla_de_cuotas_en_interes_fijo() -> None:
    """`prestamo.cuotas` vale 0 acá (no hay cuadro): "1/0 cuota pend." no diría
    nada. Lo que se debe son períodos de 30 días."""
    p = _prestamo()
    _devengar(p, date(2026, 4, 9))
    assert _detalle_prestamo(p) == "Interés fijo · 2 períodos impagos"


def test_el_renglon_del_prestamo_normal_no_cambio() -> None:
    normal = Prestamo(
        id=uuid.uuid4(), cliente_id=uuid.uuid4(), tipo_prestamo=PrestamoTipo.NORMAL,
        credito=Decimal("100000"), moneda=Moneda.ARS, cuotas=3,
        frecuencia=FrecuenciaCuotas.MENSUAL, total_a_cobrar=Decimal("120000"),
        ganancia=Decimal("20000"), estado=PrestamoEstado.ACTIVO,
        fecha_inicio=date(2026, 1, 1), cuotas_detalle=[],
    )
    normal.cuotas_detalle = [
        Cuota(id=uuid.uuid4(), prestamo=normal, numero_cuota=n,
              fecha_vencimiento=date(2026, 2, 1), monto=Decimal("40000"),
              monto_pagado=Decimal("0.00"), estado=CuotaEstado.PENDIENTE)
        for n in (1, 2, 3)
    ]
    assert _detalle_prestamo(normal) == "Préstamo · 3/3 cuotas pend."


# ── El alta valida la modalidad en el borde ──────────────────────────────────

def _create(**kwargs):
    from app.schemas.prestamos import PrestamoCreate

    base = {
        "cliente_id": uuid.uuid4(),
        "credito": Decimal("100000"),
        "moneda": Moneda.ARS,
    }
    return PrestamoCreate(**{**base, **kwargs})


def test_el_interes_fijo_exige_monto_de_interes() -> None:
    with pytest.raises(ValueError, match="monto_interes_fijo"):
        _create(tipo_prestamo=PrestamoTipo.INTERES_FIJO)


def test_el_interes_fijo_rechaza_el_cuadro_de_cuotas() -> None:
    """Cargarlo con las dos cosas significa que el operador (o el modelo) no
    entendió cuál de las dos modalidades es. Mejor fallar que inventar una."""
    with pytest.raises(ValueError, match="no lleva cuadro de cuotas"):
        _create(
            tipo_prestamo=PrestamoTipo.INTERES_FIJO,
            monto_interes_fijo=Decimal("10000"),
            cuotas=3,
            frecuencia=FrecuenciaCuotas.MENSUAL,
            total_a_cobrar=Decimal("130000"),
        )


def test_el_prestamo_normal_sigue_exigiendo_su_cuadro() -> None:
    with pytest.raises(ValueError, match="cuadro de cuotas"):
        _create(cuotas=3)


def test_el_prestamo_normal_rechaza_los_campos_del_interes_fijo() -> None:
    with pytest.raises(ValueError, match="solo del préstamo a interés fijo"):
        _create(
            cuotas=3,
            frecuencia=FrecuenciaCuotas.MENSUAL,
            total_a_cobrar=Decimal("130000"),
            monto_interes_fijo=Decimal("10000"),
        )


def test_el_prestamo_normal_sigue_pidiendo_total_mayor_al_capital() -> None:
    with pytest.raises(ValueError, match="mayor o igual"):
        _create(
            cuotas=3,
            frecuencia=FrecuenciaCuotas.MENSUAL,
            total_a_cobrar=Decimal("90000"),
        )
