"""La plata que está en la calle, en el reporte de cierre (§7).

El reporte muestra, al lado de lo que el negocio debe, lo que tiene **afuera**:
los créditos por un lado y los deudores por el otro. La suma por moneda la hace
SQL —no hay nada que probar ahí— pero cuánto falta cobrar de UN préstamo sí tiene
una regla, y es la que distingue las dos modalidades.
"""
from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from app.db.models import (
    Cuota,
    CuotaEstado,
    FrecuenciaCuotas,
    Moneda,
    Prestamo,
    PrestamoEstado,
    PrestamoTipo,
)
from app.services.reportes import _falta_cobrar

HOY = date(2026, 9, 14)


def _normal(cuotas: list[str], pagado: list[str] | None = None, cobradas: int = 0) -> Prestamo:
    """Préstamo con cuadro de cuotas; las primeras `cobradas` ya están COBRADAS."""
    total = sum((Decimal(c) for c in cuotas), Decimal("0.00"))
    p = Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        credito=total,
        moneda=Moneda.ARS,
        cuotas=len(cuotas),
        frecuencia=FrecuenciaCuotas.MENSUAL,
        total_a_cobrar=total,
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=HOY,
    )
    p.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=p.id,
            numero_cuota=i + 1,
            fecha_vencimiento=HOY,
            monto=Decimal(monto),
            monto_pagado=Decimal(pagado[i]) if pagado else Decimal("0.00"),
            estado=CuotaEstado.COBRADA if i < cobradas else CuotaEstado.PENDIENTE,
        )
        for i, monto in enumerate(cuotas)
    ]
    return p


def _interes_fijo(capital_pendiente: str, intereses: list[str], cobrados: int = 0) -> Prestamo:
    """Préstamo a interés fijo: el capital no vive en ninguna cuota (§3.b)."""
    p = Prestamo(
        id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        credito=Decimal("1000000.00"),
        moneda=Moneda.ARS,
        cuotas=0,
        frecuencia=FrecuenciaCuotas.CADA_30_DIAS,
        total_a_cobrar=Decimal("1000000.00"),
        ganancia=Decimal("0.00"),
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=HOY,
        tipo_prestamo=PrestamoTipo.INTERES_FIJO,
        monto_interes_fijo=Decimal("100000.00"),
        dia_cobro=HOY,
        capital_pendiente=Decimal(capital_pendiente),
    )
    p.cuotas_detalle = [
        Cuota(
            id=uuid.uuid4(),
            prestamo_id=p.id,
            numero_cuota=i + 1,
            fecha_vencimiento=HOY,
            monto=Decimal(monto),
            monto_pagado=Decimal("0.00"),
            estado=CuotaEstado.COBRADA if i < cobrados else CuotaEstado.PENDIENTE,
        )
        for i, monto in enumerate(intereses)
    ]
    return p


# ── Préstamo normal: lo que falta cobrar es el saldo del cuadro ───────────


def test_un_prestamo_recien_dado_esta_entero_en_la_calle() -> None:
    assert _falta_cobrar(_normal(["100000", "100000", "100000"])) == Decimal("300000.00")


def test_lo_ya_cobrado_sale_de_la_calle() -> None:
    """Un préstamo cobrado a medias ya no está entero afuera: volvió una parte."""
    p = _normal(["100000", "100000", "100000"], cobradas=1)
    assert _falta_cobrar(p) == Decimal("200000.00")


def test_un_pago_parcial_tambien_descuenta() -> None:
    """El importe libre deja una cuota a medias, y esa mitad ya volvió."""
    p = _normal(["100000", "100000"], pagado=["40000", "0"])
    assert _falta_cobrar(p) == Decimal("160000.00")


def test_un_prestamo_cobrado_entero_no_esta_en_la_calle() -> None:
    assert _falta_cobrar(_normal(["100000", "100000"], cobradas=2)) == Decimal("0.00")


# ── Interés fijo: el capital TAMBIÉN está afuera ──────────────────────────


def test_el_capital_del_interes_fijo_cuenta_como_plata_en_la_calle() -> None:
    """La diferencia con `saldo_prestamo`, y el motivo de que este helper exista.

    Ahí el capital no entra porque la pregunta es contra qué imputa un pago a
    cuenta; acá la pregunta es cuánta plata está afuera, y un millón prestado lo
    está. Sin esto, este préstamo mostraría $100.000 en la calle en vez de
    $1.100.000: el reporte diría que casi no hay nada afuera.
    """
    p = _interes_fijo("1000000", ["100000"])
    assert _falta_cobrar(p) == Decimal("1100000.00")


def test_la_mora_del_interes_fijo_se_acumula_sobre_el_capital() -> None:
    """Dos períodos impagos se deben los dos, y el capital sigue entero afuera."""
    p = _interes_fijo("1000000", ["100000", "100000"])
    assert _falta_cobrar(p) == Decimal("1200000.00")


def test_el_interes_ya_cobrado_no_cuenta_pero_el_capital_sigue() -> None:
    """Pagar el interés no baja el capital: sigue prestado hasta que lo devuelva."""
    p = _interes_fijo("1000000", ["100000", "100000"], cobrados=2)
    assert _falta_cobrar(p) == Decimal("1000000.00")


def test_devuelto_el_capital_y_saldado_el_interes_no_queda_nada_afuera() -> None:
    p = _interes_fijo("0", ["100000"], cobrados=1)
    assert _falta_cobrar(p) == Decimal("0.00")
