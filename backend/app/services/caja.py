"""caja.py — Registro de movimientos en el libro de caja.

Helper único que usan los servicios de negocio para asentar un movimiento de
efectivo (ingreso o egreso) dentro de su propia transacción. NO hace commit:
la fila se agrega a la sesión y se persiste con el commit del caller, de modo
que el movimiento de caja y la operación de negocio son atómicos (o ambos o
ninguno).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.db.models import CajaCategoria, CajaTipo, MedioPago, Moneda, MovimientoCaja


def registrar(
    db: Session,
    *,
    fecha: date,
    moneda: Moneda,
    tipo: CajaTipo,
    categoria: CajaCategoria,
    monto: Decimal,
    referencia_tipo: str | None = None,
    referencia_id: uuid.UUID | None = None,
    detalle: str | None = None,
    ganancia: Decimal | None = None,
    medio_pago: MedioPago | None = None,
    cotizacion: Decimal | None = None,
) -> MovimientoCaja:
    """Agrega (sin commit) un movimiento de caja a la sesión y lo devuelve.

    `monto` siempre positivo; el sentido lo da `tipo` (INGRESO/EGRESO).
    `ganancia` solo se usa en VENTA_USD (ganancia FIFO en ARS).
    `medio_pago` solo en pagos de pasivo (efectivo/transferencia).
    `cotizacion` ($/USD) solo cuando un pago cruza monedas (deuda y pago en
    monedas distintas); null si comparten moneda.
    """
    mov = MovimientoCaja(
        fecha=fecha,
        moneda=moneda,
        tipo=tipo,
        categoria=categoria,
        monto=Decimal(monto).quantize(Decimal("0.01")),
        ganancia=None if ganancia is None else Decimal(ganancia).quantize(Decimal("0.01")),
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        detalle=detalle,
        medio_pago=medio_pago,
        cotizacion=None if cotizacion is None else Decimal(cotizacion).quantize(Decimal("0.0001")),
    )
    db.add(mov)
    return mov


def borrar_por_referencia(
    db: Session, referencia_tipo: str, referencia_id: uuid.UUID
) -> None:
    """Elimina (sin commit) los movimientos de caja de una entidad origen.

    Lo usan las ediciones que rehacen el impacto de caja de una operación
    (ej. corregir el monto de un gasto ya asentado)."""
    db.query(MovimientoCaja).filter(
        MovimientoCaja.referencia_tipo == referencia_tipo,
        MovimientoCaja.referencia_id == referencia_id,
    ).delete(synchronize_session=False)
