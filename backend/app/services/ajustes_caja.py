"""ajustes_caja.py — Agregar o restar efectivo de la caja a mano.

Hasta acá la caja solo se movía como consecuencia de una operación de negocio: un
cobro, un gasto, una compra. Un ajuste es la excepción explícita — plata que entra
o sale **sin** operación detrás:

- **CORRECCION** — el sistema no coincide con el efectivo real del cajón.
- **APORTE** / **RETIRO** — el dueño puso o sacó plata del negocio.
- **OTRO** — cualquier otra razón; exige descripción.

Cada ajuste asienta una línea `AJUSTE_CAJA` en el libro con su `tipo`, así que
**cuenta como ingreso o egreso del período** (decisión del dueño, 2026-08-10). Un
aporte va a levantar el neto del día como si hubiera sido un buen día de operación:
es a propósito, el neto sigue siendo el flujo real de caja.

**Dólares — el efectivo no alcanza, hace falta el stock.** La caja USD y el stock
vendible son cosas distintas: la venta consume **lotes** `MovimientoEfectivo` (§4).
Por eso un ajuste que suma USD exige la `cotizacion_usd` a la que se consiguieron y
crea su lote (`es_ajuste=True`), y uno que resta USD **consume lotes FIFO sin
realizar ganancia** —esos dólares se fueron, pero nadie los compró—. Sin esto el
reporte mostraría dólares que no se pueden vender, o stock de dólares que ya no
están.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    AjusteCaja,
    AjusteCajaMotivo,
    CajaCategoria,
    CajaTipo,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.services import caja as svc_caja
from app.services.exceptions import (
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CERO = Decimal("0.00")
_REF = "ajuste_caja"

_LABEL_MOTIVO: dict[AjusteCajaMotivo, str] = {
    AjusteCajaMotivo.CORRECCION: "Corrección de caja",
    AjusteCajaMotivo.APORTE:     "Aporte del dueño",
    AjusteCajaMotivo.RETIRO:     "Retiro del dueño",
    AjusteCajaMotivo.OTRO:       "Ajuste de caja",
}


def _detalle(ajuste: AjusteCaja) -> str:
    """Texto de la línea del libro. El reporte lo muestra tal cual."""
    base = _LABEL_MOTIVO[ajuste.motivo]
    if ajuste.descripcion and ajuste.descripcion.strip():
        return f"{base}: {ajuste.descripcion.strip()}"
    return base


def crear_ajuste(
    db: Session,
    *,
    fecha: date,
    moneda: Moneda,
    tipo: CajaTipo,
    motivo: AjusteCajaMotivo,
    monto: Decimal,
    operador_id: str,
    cotizacion_usd: Decimal | None = None,
    descripcion: str | None = None,
) -> AjusteCaja:
    """Registra un ajuste y asienta su línea en el libro de caja.

    `monto` es siempre positivo: el sentido lo da `tipo` (INGRESO suma efectivo,
    EGRESO lo resta). Lanza `ValidationError` si al restar dólares no hay stock
    suficiente en los lotes.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador que hace el ajuste.")
    if monto is None or Decimal(monto) <= 0:
        raise ValidationError("El monto del ajuste tiene que ser mayor a cero.")
    # Sin razón escrita, dentro de un mes nadie va a poder reconstruir por qué la
    # caja se movió sola. Es justamente el dato que hace auditable el ajuste.
    if motivo == AjusteCajaMotivo.OTRO and not (descripcion and descripcion.strip()):
        raise ValidationError(
            "Contá brevemente el motivo del ajuste: es lo que permite entender "
            "después por qué se tocó la caja."
        )

    monto = Decimal(monto).quantize(Decimal("0.01"))
    suma_usd = moneda == Moneda.USD and tipo == CajaTipo.INGRESO

    # Sin costo no hay lote, y sin lote esos dólares quedan en la caja pero no se
    # pueden vender: mejor frenar acá que descubrirlo al intentar venderlos.
    if suma_usd and (cotizacion_usd is None or Decimal(cotizacion_usd) <= 0):
        raise ValidationError(
            "Indicá a qué cotización ($/USD) se consiguieron esos dólares: es el "
            "costo contra el que se calcula la ganancia cuando se vendan."
        )
    if not suma_usd:
        # La cotización solo tiene sentido cuando el ajuste crea un lote.
        cotizacion_usd = None

    ajuste = AjusteCaja(
        fecha=fecha,
        moneda=moneda,
        tipo=tipo,
        motivo=motivo,
        monto=monto,
        cotizacion_usd=Decimal(cotizacion_usd) if cotizacion_usd is not None else None,
        descripcion=(descripcion or "").strip() or None,
        operador_id=operador_id.strip(),
    )

    try:
        db.add(ajuste)

        if suma_usd:
            lote = _crear_lote(db, ajuste)
            db.flush()
            ajuste.lote_id = lote.id

        # La sesión va con autoflush=False: sin este flush, el SELECT de
        # _reimputar_fifo no ve el ajuste recién agregado y no lo imputaría.
        db.flush()

        if moneda == Moneda.USD:
            from app.services.movimientos import _reimputar_fifo

            # Recalcular la cadena entera cubre los dos casos: valida que haya
            # stock para restar y reubica el ajuste si se cargó con fecha vieja.
            _reimputar_fifo(db)

        svc_caja.registrar(
            db,
            fecha=fecha,
            moneda=moneda,
            tipo=tipo,
            categoria=CajaCategoria.AJUSTE_CAJA,
            monto=monto,
            referencia_tipo=_REF,
            referencia_id=ajuste.id,
            detalle=_detalle(ajuste),
        )

        db.commit()
        db.refresh(ajuste)
        return ajuste
    except ValidationError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el ajuste de caja.") from exc


def _crear_lote(db: Session, ajuste: AjusteCaja) -> MovimientoEfectivo:
    """Crea el lote FIFO de un ajuste que suma dólares.

    Se inserta directo, sin pasar por `create_movimiento`, para que **no asiente
    caja**: la caja USD ya la mueve la línea `AJUSTE_CAJA` del propio ajuste, y una
    compra además restaría pesos que nunca salieron. Mismo criterio que el lote de
    apertura (§Apertura).
    """
    lote = MovimientoEfectivo(
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=ajuste.monto,
        cotizacion_aplicada=ajuste.cotizacion_usd,
        ganancia=_CERO,
        usd_restante=ajuste.monto,  # lote intacto: nada consumido todavía
        fecha_operacion=datetime.combine(ajuste.fecha, time.min, tzinfo=UTC),
        observaciones=f"Stock por ajuste de caja ({_LABEL_MOTIVO[ajuste.motivo]})",
        es_ajuste=True,
    )
    db.add(lote)
    return lote


def list_ajustes(
    db: Session, desde: date | None = None, hasta: date | None = None
) -> list[AjusteCaja]:
    stmt = select(AjusteCaja).where(AjusteCaja.anulado_at.is_(None))
    if desde is not None:
        stmt = stmt.where(AjusteCaja.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(AjusteCaja.fecha <= hasta)
    return list(
        db.scalars(stmt.order_by(AjusteCaja.fecha.desc(), AjusteCaja.created_at.desc()))
    )


def get_ajuste(db: Session, ajuste_id: uuid.UUID) -> AjusteCaja:
    ajuste = db.get(AjusteCaja, ajuste_id)
    if ajuste is None:
        raise NotFoundError("Ajuste de caja no encontrado.")
    return ajuste
