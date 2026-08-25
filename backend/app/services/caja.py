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
    medio_pago: MedioPago,
    referencia_tipo: str | None = None,
    referencia_id: uuid.UUID | None = None,
    detalle: str | None = None,
    ganancia: Decimal | None = None,
    cotizacion: Decimal | None = None,
) -> MovimientoCaja:
    """Agrega (sin commit) un movimiento de caja a la sesión y lo devuelve.

    `monto` siempre positivo; el sentido lo da `tipo` (INGRESO/EGRESO).

    `medio_pago` dice **por cuál de las dos cajas** pasó la plata, y por eso no
    tiene default: cada moneda lleva dos saldos paralelos —el efectivo del cajón
    y la plata del banco— y un movimiento sin medio no pertenecería a ninguno de
    los dos. Que sea obligatorio es a propósito: una operación nueva no puede
    olvidárselo en silencio y quedar fuera de los dos cierres.

    `ganancia` solo se usa en VENTA_USD (ganancia FIFO en ARS).
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


def borrar_por_referencia_tipo(db: Session, referencia_tipo: str) -> None:
    """Elimina (sin commit) TODAS las líneas de un tipo de referencia.

    Para asientos que no cuelgan de una entidad con id propio, como el saldo de
    apertura (`referencia_tipo='apertura'`): al rehacerlo hay que limpiar el
    anterior completo, porque no hay un `referencia_id` por el cual filtrar."""
    db.query(MovimientoCaja).filter(
        MovimientoCaja.referencia_tipo == referencia_tipo,
    ).delete(synchronize_session=False)


def borrar_por_referencia(
    db: Session,
    referencia_tipo: str,
    referencia_id: uuid.UUID,
    categoria: CajaCategoria | None = None,
) -> None:
    """Elimina (sin commit) los movimientos de caja de una entidad origen.

    Lo usan las ediciones que rehacen el impacto de caja de una operación
    (ej. corregir el monto de un gasto ya asentado).

    `categoria` acota el barrido a un solo tipo de línea. Hace falta cuando una
    misma entidad asienta líneas de significados distintos bajo la misma
    referencia: un pasivo lleva el INGRESO_PASIVO de su alta y un PAGO_PASIVO por
    cada pago, y rehacer el primero no debe borrar los segundos —esa plata salió
    de verdad—."""
    q = db.query(MovimientoCaja).filter(
        MovimientoCaja.referencia_tipo == referencia_tipo,
        MovimientoCaja.referencia_id == referencia_id,
    )
    if categoria is not None:
        q = q.filter(MovimientoCaja.categoria == categoria)
    q.delete(synchronize_session=False)


def medio_de_referencia(
    db: Session,
    referencia_tipo: str,
    referencia_id: uuid.UUID,
    categoria: CajaCategoria | None = None,
    *,
    moneda: Moneda | None = None,
    default: MedioPago = MedioPago.EFECTIVO,
) -> MedioPago:
    """Con qué medio se había asentado una operación, para no perderlo al rehacerla.

    Las ediciones que cambian el monto o la fecha borran la línea de caja y la
    vuelven a escribir (`borrar_por_referencia` + `registrar`). Si el operador no
    dijo nada del medio, corregir el monto de un gasto pagado por transferencia lo
    devolvería al efectivo en silencio y descuadraría las **dos** cajas de una: una
    de más y la otra de menos. Acá se lee el medio anterior antes de borrar.

    `moneda` hace falta cuando una operación asienta **dos** líneas de la misma
    categoría en monedas distintas —una compra de dólares saca pesos y mete USD—:
    cada pata pudo ir por una caja distinta y sin el filtro se leería la primera.

    `default` es para lo que no tenga línea previa (una operación que recién ahora
    empieza a asentar caja).
    """
    mov = (
        db.query(MovimientoCaja)
        .filter(
            MovimientoCaja.referencia_tipo == referencia_tipo,
            MovimientoCaja.referencia_id == referencia_id,
            *([MovimientoCaja.categoria == categoria] if categoria is not None else []),
            *([MovimientoCaja.moneda == moneda] if moneda is not None else []),
        )
        .order_by(MovimientoCaja.created_at.asc())
        .first()
    )
    return mov.medio_pago if mov is not None else default
