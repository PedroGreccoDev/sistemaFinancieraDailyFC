"""stock_usd.py — El stock vendible de dólares, para las operaciones que no son divisas.

**La caja USD y el stock vendible son cosas distintas** (§4). La caja dice cuántos
dólares hay; el stock son los **lotes** `MovimientoEfectivo` con su costo, que es
contra lo que se calcula la ganancia FIFO cuando se venden. Un dólar que figura
en la caja pero no en un lote no se puede vender —la venta falla con "no hay
stock"—, y uno que salió de la caja sin consumir lote sigue contando como
vendible y presta su costo a una ganancia futura que ya no tiene respaldo.

Hasta la migración `0025` solo movían stock la compra/venta de divisas, la
apertura, los ajustes y el préstamo recibido en dólares. Este módulo cierra el
resto: **toda** entrada o salida de dólares mueve el stock, y lo hace con la
pieza que ya existía —un `MovimientoEfectivo` marcado `es_ajuste`, que es "stock
que se movió sin una operación de divisas detrás": no asienta caja (la mueve la
operación de negocio) y no figura en el listado de Divisas—.

- **Entra** como `COMPRA`: aporta stock al costo que **declara el operador**. La
  cotización jamás se asume (regla 1 del bot, §4): de ese número depende la
  ganancia del día que se vendan, y para cuando eso pase nadie se acuerda a
  cuánto estaba el dólar.
- **Sale** como `VENTA`: consume lotes FIFO **sin realizar ganancia** —esos
  dólares se fueron, pero nadie los compró—, igual que un ajuste que resta USD.

`origen_tipo`/`origen_id` enlazan el movimiento con la operación que lo generó,
para poder deshacerlo cuando esa operación se edita o se anula.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import Moneda, MovimientoEfectivo, MovimientoEfectivoTipo
from app.services.exceptions import ValidationError

_CERO = Decimal("0.00")


def _momento_operativo(fecha: date | None) -> datetime:
    """Dónde se ubica este movimiento en la cadena FIFO, que se ordena por tiempo.

    **Del día de hoy se usa la hora real**, porque es cuando de verdad ocurrió y
    el FIFO tiene que consumir en ese orden: fechar al arranque del día un cobro
    hecho a la tarde lo pondría antes de la compra de la mañana, y una venta
    posterior saldría del lote equivocado —con la ganancia calculada contra un
    costo que no correspondía—.

    De una fecha pasada solo se sabe el día (estas operaciones no guardan hora),
    así que se la ubica al arranque: es lo único que se puede afirmar, y no
    reordena entre sí las ventas de divisas de ese día. Mismo criterio que
    `_orden_ajuste` para los ajustes de caja."""
    hoy = hoy_local()
    if fecha is None or fecha == hoy:
        return datetime.now(UTC)
    return datetime.combine(fecha, time.min, tzinfo=UTC)


def ingresar(
    db: Session,
    *,
    monto: Decimal,
    cotizacion: Decimal | None,
    fecha: date | None,
    origen_tipo: str,
    origen_id: uuid.UUID,
    detalle: str,
) -> MovimientoEfectivo:
    """Suma dólares al stock vendible, al costo que declaró el operador (sin commit).

    Raises:
        ValidationError: si no vino la cotización. **No se asume ninguna**: sin
            costo esos dólares no se podrían vender, y descubrirlo el día de la
            venta es tarde.
    """
    if cotizacion is None or Decimal(cotizacion) <= 0:
        raise ValidationError(
            "Para que esos dólares queden disponibles para vender hace falta a "
            "cuánto los tomás: indicá la cotización (pesos por 1 USD)."
        )
    lote = MovimientoEfectivo(
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=Decimal(monto).quantize(Decimal("0.01")),
        cotizacion_aplicada=Decimal(cotizacion),
        ganancia=_CERO,
        usd_restante=Decimal(monto).quantize(Decimal("0.01")),  # intacto
        fecha_operacion=_momento_operativo(fecha),
        observaciones=detalle,
        es_ajuste=True,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )
    db.add(lote)
    db.flush()
    return lote


def egresar(
    db: Session,
    *,
    monto: Decimal,
    fecha: date | None,
    origen_tipo: str,
    origen_id: uuid.UUID,
    detalle: str,
) -> MovimientoEfectivo:
    """Saca dólares del stock vendible (sin commit): consume lotes FIFO, sin ganancia.

    No lleva cotización: el costo lo ponen los lotes que se consumen. El consumo
    en sí lo hace `_reimputar_fifo`, que es quien recorre la cadena entera —acá
    solo se agrega el movimiento que la reimputación va a ver—.
    """
    salida = MovimientoEfectivo(
        tipo=MovimientoEfectivoTipo.VENTA,
        moneda=Moneda.USD,
        monto=Decimal(monto).quantize(Decimal("0.01")),
        # La venta exige una cotización > 0 por check de tabla, pero acá no hubo
        # precio de venta: no se vendieron, se fueron. Se marca en 1 y la
        # ganancia queda en 0 — `_reimputar_fifo` saltea el cálculo por `es_ajuste`.
        cotizacion_aplicada=Decimal("1"),
        ganancia=_CERO,
        usd_restante=_CERO,
        fecha_operacion=_momento_operativo(fecha),
        observaciones=detalle,
        es_ajuste=True,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )
    db.add(salida)
    db.flush()
    return salida


def listar_por_origen(
    db: Session, origen_tipo: str, origen_id: uuid.UUID
) -> list[MovimientoEfectivo]:
    return list(
        db.scalars(
            select(MovimientoEfectivo).where(
                MovimientoEfectivo.origen_tipo == origen_tipo,
                MovimientoEfectivo.origen_id == origen_id,
            )
        )
    )


def borrar_por_origen(db: Session, origen_tipo: str, origen_id: uuid.UUID) -> None:
    """Saca de la cadena los movimientos de stock de una operación (sin commit).

    Para rehacerlos al editar la operación, o al anularla. **Se valida antes de
    borrar nada**: si un lote que aportó stock ya fue vendido en parte, quitarlo
    dejaría esa venta sin el stock del que salió y reescribiría su ganancia ya
    reportada. Mismo criterio que anular un ajuste en USD (§Ajustes de caja) o
    editar un préstamo recibido en dólares (§5).
    """
    movimientos = listar_por_origen(db, origen_tipo, origen_id)
    for mov in movimientos:
        if mov.tipo == MovimientoEfectivoTipo.COMPRA and mov.usd_restante != mov.monto:
            consumido = mov.monto - mov.usd_restante
            raise ValidationError(
                f"No se puede deshacer: {consumido} de los {mov.monto} USD que "
                "entraron con esta operación ya se vendieron. Anulá primero esas ventas."
            )
    for mov in movimientos:
        db.delete(mov)
