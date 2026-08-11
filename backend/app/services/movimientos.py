from __future__ import annotations

import uuid
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import fecha_local
from app.db.models import (
    AjusteCaja,
    CajaCategoria,
    CajaTipo,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.schemas.movimientos import MovimientoEfectivoCreate, MovimientoEfectivoUpdate
from app.services import caja as svc_caja
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CERO = Decimal("0.00")
_REF = "movimiento_efectivo"


def consumir_lotes_fifo(
    lotes: list[tuple[Decimal, Decimal]],
    cantidad: Decimal,
    *,
    accion: str = "vender",
) -> list[Decimal]:
    """Reparte `cantidad` de USD sobre los lotes en orden FIFO (los más viejos primero).

    `lotes` es una lista de `(costo_unitario, cantidad_restante)` ya ordenada del
    más viejo al más nuevo. Devuelve `consumos`, donde `consumos[i]` es la cantidad
    de USD tomada del lote i.

    Es la primitiva de stock, sin plata de por medio: la usa la venta —que además
    calcula ganancia— y también el ajuste manual que resta dólares de la caja, que
    consume stock sin realizar ninguna ganancia (§Ajustes de caja).

    `accion` solo arma el mensaje de error. Lanza `ValidationError` si el stock
    total de los lotes no alcanza.
    """
    cantidad = Decimal(cantidad)
    disponible = sum((r for _, r in lotes), _CERO)
    if cantidad > disponible:
        raise ValidationError(
            f"No hay stock de USD suficiente: se intentó {accion} {cantidad} y "
            f"hay {disponible} en cartera."
        )

    consumos: list[Decimal] = [_CERO] * len(lotes)
    pendiente = cantidad
    for i, (_costo, restante) in enumerate(lotes):
        if pendiente <= 0:
            break
        tomar = min(restante, pendiente)
        if tomar <= 0:
            continue
        consumos[i] = tomar
        pendiente -= tomar

    return consumos


def calcular_ganancia_fifo(
    lotes: list[tuple[Decimal, Decimal]],
    cantidad: Decimal,
    precio_venta: Decimal,
) -> tuple[Decimal, list[Decimal]]:
    """Imputa una venta de divisas contra los lotes de compra en orden FIFO.

    `lotes` es una lista de `(costo_unitario, cantidad_restante)` ya ordenada del
    más viejo al más nuevo. Devuelve `(ganancia_total_ARS, consumos)` donde
    `consumos[i]` es la cantidad de USD tomada del lote i. La ganancia es exacta,
    sin promedios: cada tramo aporta `(precio_venta − costo_lote) × cantidad`.

    Lanza `ValidationError` si el stock total de los lotes no alcanza.
    """
    consumos = consumir_lotes_fifo(lotes, cantidad)
    ganancia = _CERO
    for (costo, _restante), consumo in zip(lotes, consumos):
        if consumo > 0:
            ganancia += (precio_venta - costo) * consumo

    return ganancia.quantize(Decimal("0.01")), consumos


def create_movimiento(
    db: Session,
    payload: MovimientoEfectivoCreate,
) -> MovimientoEfectivo:
    fecha_caja = fecha_local(payload.fecha_operacion)
    monto = payload.monto
    cotiz = payload.cotizacion_aplicada
    pesos = (monto * cotiz).quantize(Decimal("0.01"))

    movimiento = MovimientoEfectivo(
        cliente_id=payload.cliente_id,
        tipo=payload.tipo,
        moneda=payload.moneda,
        monto=monto,
        cotizacion_aplicada=cotiz,
        observaciones=payload.observaciones,
    )
    if payload.fecha_operacion is not None:
        movimiento.fecha_operacion = payload.fecha_operacion

    try:
        if payload.tipo == MovimientoEfectivoTipo.COMPRA:
            # La compra incorpora USD al stock a su costo real (lote FIFO).
            movimiento.usd_restante = monto
            movimiento.ganancia = _CERO
            db.add(movimiento)
            db.flush()

            detalle = f"Compra de {monto} USD @ ${cotiz}"
            # Salen pesos de la caja ARS, entran dólares a la caja USD.
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.COMPRA_USD, monto=pesos,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.COMPRA_USD, monto=monto,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
        else:
            # Venta: imputa contra los lotes de compra (FIFO) y realiza la ganancia.
            lotes_rows = list(
                db.scalars(
                    select(MovimientoEfectivo)
                    .where(
                        MovimientoEfectivo.tipo == MovimientoEfectivoTipo.COMPRA,
                        MovimientoEfectivo.usd_restante > 0,
                        MovimientoEfectivo.anulado_at.is_(None),
                    )
                    .order_by(
                        MovimientoEfectivo.fecha_operacion.asc(),
                        MovimientoEfectivo.created_at.asc(),
                    )
                    .with_for_update()
                )
            )
            lotes = [(r.cotizacion_aplicada, r.usd_restante) for r in lotes_rows]
            ganancia, consumos = calcular_ganancia_fifo(lotes, monto, cotiz)
            for row, consumo in zip(lotes_rows, consumos):
                if consumo > 0:
                    row.usd_restante = (row.usd_restante - consumo).quantize(Decimal("0.01"))

            movimiento.usd_restante = _CERO
            movimiento.ganancia = ganancia
            db.add(movimiento)
            db.flush()

            detalle = f"Venta de {monto} USD @ ${cotiz}"
            # Entran pesos a la caja ARS, salen dólares de la caja USD.
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.VENTA_USD, monto=pesos, ganancia=ganancia,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )
            svc_caja.registrar(
                db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.VENTA_USD, monto=monto,
                referencia_tipo=_REF, referencia_id=movimiento.id, detalle=detalle,
            )

        db.commit()
        db.refresh(movimiento)
        return movimiento
    except ValidationError:
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el movimiento de efectivo.") from exc


def list_movimientos(db: Session) -> list[MovimientoEfectivo]:
    # Los lotes creados por un ajuste manual de caja aportan stock al FIFO pero no
    # son operaciones de divisas: mostrarlos acá los haría pasar por compras que
    # nunca ocurrieron. El ajuste ya se ve como ajuste (§Ajustes de caja).
    return list(
        db.scalars(
            select(MovimientoEfectivo)
            .where(
                MovimientoEfectivo.anulado_at.is_(None),
                MovimientoEfectivo.es_ajuste.is_(False),
            )
            .order_by(MovimientoEfectivo.created_at.desc())
        )
    )


def get_movimiento(db: Session, movimiento_id: uuid.UUID) -> MovimientoEfectivo:
    mov = db.get(MovimientoEfectivo, movimiento_id)
    if mov is None:
        raise NotFoundError("Movimiento de efectivo no encontrado.")
    return mov


def _orden_ajuste(ajuste: AjusteCaja) -> tuple[datetime, datetime]:
    """Clave de orden de un ajuste dentro de la cadena FIFO.

    Un ajuste solo guarda el **día**, no la hora. Se lo ubica al arranque de su día
    para no alterar el orden relativo de las ventas entre sí, que se comparan por
    `fecha_operacion` completa: si se las reordenara por día se reescribirían
    ganancias FIFO ya reportadas.
    """
    # `created_at` lo pone la BD (server_default): recién insertado puede no estar
    # cargado todavía, y comparar tuplas contra None rompe el sort.
    creado = ajuste.created_at or datetime.min.replace(tzinfo=UTC)
    return (datetime.combine(ajuste.fecha, time.min, tzinfo=UTC), creado)


def _consumidores_de_stock(db: Session, movs: list[MovimientoEfectivo]) -> list:
    """Todo lo que saca dólares del stock, en orden cronológico.

    Son dos cosas: las **ventas** de divisas y los **ajustes manuales que restan
    USD** de la caja (§Ajustes de caja). Los ajustes también consumen lotes —esos
    dólares se fueron— pero no realizan ganancia: no hubo precio de venta.
    """
    ajustes = list(
        db.scalars(
            select(AjusteCaja)
            .where(
                AjusteCaja.anulado_at.is_(None),
                AjusteCaja.moneda == Moneda.USD,
                AjusteCaja.tipo == CajaTipo.EGRESO,
            )
            .with_for_update()
        )
    )
    consumidores = [
        ((v.fecha_operacion, v.created_at), v)
        for v in movs
        if v.tipo == MovimientoEfectivoTipo.VENTA
    ]
    consumidores += [(_orden_ajuste(a), a) for a in ajustes]
    consumidores.sort(key=lambda par: par[0])
    return [item for _clave, item in consumidores]


def _reimputar_fifo(db: Session) -> None:
    """Recalcula toda la cadena FIFO de divisas desde cero (sin commit).

    Resetea el stock de cada lote (`usd_restante = monto`) y vuelve a imputar en
    orden cronológico todo lo que consume stock —ventas y ajustes que restan USD—,
    recomputando la ganancia de cada venta. Es la forma robusta de reflejar una
    edición sin arrastrar el estado previo. Como editar solo se permite sobre lotes
    intactos y la última venta, esto reproduce idénticamente el resto de las
    operaciones y solo cambia la editada.

    **Los ajustes tienen que entrar acá.** Como esta función resetea el stock de
    todos los lotes, un consumo hecho por fuera se restauraría solo y en silencio
    la próxima vez que alguien editara o anulara una operación de divisas.
    """
    # Las operaciones anuladas salen de la cadena: no aportan stock ni consumen lotes.
    movs = list(
        db.scalars(
            select(MovimientoEfectivo)
            .where(MovimientoEfectivo.anulado_at.is_(None))
            .order_by(
                MovimientoEfectivo.fecha_operacion.asc(),
                MovimientoEfectivo.created_at.asc(),
            )
            .with_for_update()
        )
    )
    for m in movs:
        if m.tipo == MovimientoEfectivoTipo.COMPRA:
            m.usd_restante = m.monto

    for item in _consumidores_de_stock(db, movs):
        lotes_rows = [
            c
            for c in movs
            if c.tipo == MovimientoEfectivoTipo.COMPRA and c.usd_restante > 0
        ]
        lotes = [(c.cotizacion_aplicada, c.usd_restante) for c in lotes_rows]

        if isinstance(item, AjusteCaja):
            # Salieron dólares de la caja sin venderse: consume stock, sin ganancia.
            consumos = consumir_lotes_fifo(
                lotes, item.monto, accion="restar de la caja"
            )
        else:
            ganancia, consumos = calcular_ganancia_fifo(
                lotes, item.monto, item.cotizacion_aplicada
            )
            item.ganancia = ganancia
            item.usd_restante = _CERO

        for row, consumo in zip(lotes_rows, consumos):
            if consumo > 0:
                row.usd_restante = (row.usd_restante - consumo).quantize(Decimal("0.01"))


def _resync_caja_movimiento(db: Session, mov: MovimientoEfectivo) -> None:
    """Reconstruye las dos líneas de caja (ARS + USD) de una operación de divisas."""
    svc_caja.borrar_por_referencia(db, _REF, mov.id)
    # El lote de apertura nunca asentó caja —los pesos salieron antes de que el
    # sistema existiera, y la caja USD la aporta la línea SALDO_INICIAL—, así que
    # resincronizar no debe inventarle movimientos: duplicaría los dólares.
    # Lo mismo vale para el lote de un ajuste manual: la caja USD ya la movió la
    # línea AJUSTE_CAJA del propio ajuste (§Ajustes de caja).
    if mov.es_apertura or mov.es_ajuste:
        return
    fecha_caja = fecha_local(mov.fecha_operacion)
    pesos = (mov.monto * mov.cotizacion_aplicada).quantize(Decimal("0.01"))
    if mov.tipo == MovimientoEfectivoTipo.COMPRA:
        detalle = f"Compra de {mov.monto} USD @ ${mov.cotizacion_aplicada}"
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.COMPRA_USD, monto=pesos,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.INGRESO,
            categoria=CajaCategoria.COMPRA_USD, monto=mov.monto,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
    else:
        detalle = f"Venta de {mov.monto} USD @ ${mov.cotizacion_aplicada}"
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
            categoria=CajaCategoria.VENTA_USD, monto=pesos, ganancia=mov.ganancia,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )
        svc_caja.registrar(
            db, fecha=fecha_caja, moneda=Moneda.USD, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.VENTA_USD, monto=mov.monto,
            referencia_tipo=_REF, referencia_id=mov.id, detalle=detalle,
        )


def editar_movimiento(
    db: Session, movimiento_id: uuid.UUID, payload: MovimientoEfectivoUpdate
) -> MovimientoEfectivo:
    """Corrige una operación de divisas respetando la imputación FIFO.

    `cliente_id`/`observaciones` se editan siempre. `monto`/`cotizacion_aplicada`
    solo si la operación no está "trabada" en la cadena FIFO:
      - COMPRA: el lote debe estar intacto (`usd_restante == monto`).
      - VENTA: debe ser la última (no puede haber ventas posteriores).
    """
    mov = db.scalar(
        select(MovimientoEfectivo).where(MovimientoEfectivo.id == movimiento_id).with_for_update()
    )
    if mov is None:
        raise NotFoundError("Movimiento de efectivo no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "cotizacion_aplicada" in data

    if cambia_dinero:
        if mov.tipo == MovimientoEfectivoTipo.COMPRA:
            if mov.usd_restante != mov.monto:
                raise ConflictError(
                    "Esta compra ya fue consumida (total o parcialmente) por una o más "
                    "ventas en la cadena FIFO, así que no se puede editar su monto ni "
                    "cotización. Corregila registrando una operación inversa."
                )
        else:  # VENTA
            posterior = db.scalar(
                select(MovimientoEfectivo.id)
                .where(
                    MovimientoEfectivo.tipo == MovimientoEfectivoTipo.VENTA,
                    MovimientoEfectivo.id != mov.id,
                    tuple_(MovimientoEfectivo.fecha_operacion, MovimientoEfectivo.created_at)
                    > (mov.fecha_operacion, mov.created_at),
                )
                .limit(1)
            )
            if posterior is not None:
                raise ConflictError(
                    "Hay ventas posteriores que dependen de esta imputación FIFO; "
                    "solo se puede editar la última venta. Corregila con una operación "
                    "inversa o editá primero las ventas más nuevas."
                )

    if "cliente_id" in data:
        mov.cliente_id = data["cliente_id"]
    if "observaciones" in data:
        mov.observaciones = data["observaciones"]
    if "monto" in data:
        mov.monto = data["monto"]
    if "cotizacion_aplicada" in data:
        mov.cotizacion_aplicada = data["cotizacion_aplicada"]

    try:
        if mov.tipo == MovimientoEfectivoTipo.COMPRA:
            # Lote intacto: su stock disponible es su monto completo.
            mov.usd_restante = mov.monto
        # Recalcular la cadena (recompone ganancia de la venta editada y stock de lotes).
        _reimputar_fifo(db)
        _resync_caja_movimiento(db, mov)
        db.commit()
        db.refresh(mov)
        return mov
    except (ValidationError, ConflictError):
        db.rollback()
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el movimiento de efectivo.") from exc
