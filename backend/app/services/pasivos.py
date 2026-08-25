from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    MedioPago,
    Moneda,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
    Pasivo,
    PasivoEstado,
)
from app.core.fechas import fecha_local, hoy_local
from app.services import apertura as svc_apertura
from app.services import caja as svc_caja
from app.services.conversion import calcular_reduccion_saldo
from app.services.prestamos import repartir_pago_en_cuotas
from app.schemas.pasivos import (
    PasivoCancelarConChequeRequest,
    PasivoCreate,
    PasivoPagoRequest,
    PasivoUpdate,
)
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

# calcular_reduccion_saldo se movió a app.services.conversion (lo comparten pasivos,
# fiados y préstamos). Se re-exporta acá por compatibilidad con imports existentes.
__all__ = ["calcular_reduccion_saldo"]

_CERO = Decimal("0.00")
_CENTAVO = Decimal("0.01")

# Campos que forman parte de la línea `INGRESO_PASIVO` del alta: si la edición toca
# alguno, esa línea se rehace (monto, moneda y fecha son la línea misma; acreedor y
# concepto, su detalle).
_CAMPOS_INGRESO = frozenset(
    {
        "ingreso_caja", "fecha_ingreso", "cotizacion_ingreso_usd",
        "monto", "moneda", "acreedor", "concepto",
    }
)


def create_pasivo(
    db: Session,
    payload: PasivoCreate,
    created_at: datetime | None = None,
) -> Pasivo:
    """Anota una deuda del negocio.

    Por defecto **no mueve la caja**: la deuda típica es comercial —le debo al
    proveedor por la mercadería— y ahí no entró un peso, solo quedó la obligación.
    La caja se toca recién al pagarla (`PAGO_PASIVO`).

    Con `ingreso_caja` es el otro caso: **alguien le prestó plata al negocio**. La
    deuda nace igual, pero además el efectivo entró al cajón, así que el alta
    asienta el INGRESO `INGRESO_PASIVO` de `fecha_ingreso`. Sin eso el reporte del
    día quedaría corto contra la plata real.

    **Si le prestaron dólares, además hace falta el lote de stock**: la caja USD y
    lo que se puede vender son cosas distintas (§4), así que el alta exige la
    cotización con la que entran al FIFO."""
    fecha_ingreso = payload.fecha_ingreso
    if payload.ingreso_caja and fecha_ingreso is None:
        fecha_ingreso = fecha_local(created_at)
    if payload.ingreso_caja:
        _exigir_cotizacion_usd(payload.moneda, payload.cotizacion_ingreso_usd)

    pasivo = Pasivo(
        acreedor=payload.acreedor.strip(),
        concepto=payload.concepto.strip(),
        monto=payload.monto,
        saldo_pendiente=payload.monto,
        moneda=payload.moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=payload.fecha_vencimiento,
        observaciones=payload.observaciones,
        ingreso_caja=payload.ingreso_caja,
        # Se guarda solo si entró plata: una fecha suelta sin ingreso confunde.
        fecha_ingreso=fecha_ingreso if payload.ingreso_caja else None,
        cotizacion_ingreso_usd=(
            payload.cotizacion_ingreso_usd
            if payload.ingreso_caja and payload.moneda == Moneda.USD
            else None
        ),
    )
    if created_at is not None:
        pasivo.created_at = created_at
    db.add(pasivo)
    # El ingreso necesita el id del pasivo para referenciarlo, y sin flush todavía
    # no lo tiene. El commit de abajo persiste deuda y línea de caja juntas.
    db.flush()
    _registrar_ingreso(db, pasivo, payload.medio_pago)
    _crear_lote_usd(db, pasivo)
    db.commit()
    db.refresh(pasivo)
    return pasivo


def _exigir_cotizacion_usd(moneda: Moneda, cotizacion: Decimal | None) -> None:
    """Dólares prestados sin costo declarado no pueden entrar al stock.

    Y sin stock no se pueden vender: el error aparecería recién el día que se
    intente venderlos, cuando ya no se sabe a cuánto estaba el dólar aquel día.
    Mismo criterio que el saldo inicial en USD (§Apertura) y los ajustes (§Ajustes).
    La cotización la dicta el operador; el sistema no la asume nunca."""
    if moneda != Moneda.USD:
        return
    if cotizacion is None or cotizacion <= _CERO:
        raise ValidationError(
            "Decinos a cuánto valuás esos dólares ($/USD): es el costo con el que "
            "entran al stock y contra el que se calcula la ganancia si los vendés."
        )


def _crear_lote_usd(db: Session, pasivo: Pasivo) -> MovimientoEfectivo | None:
    """Crea (sin commit) el lote FIFO de unos dólares que le prestaron al negocio.

    Se inserta directo, sin pasar por `create_movimiento`, para que **no asiente
    caja**: la caja USD ya la mueve la línea `INGRESO_PASIVO`, y una compra además
    restaría pesos que nunca salieron. Mismo criterio que el lote de apertura
    (§Apertura) y el de un ajuste que suma dólares (§Ajustes de caja); comparte con
    ellos la marca `es_ajuste`, que es la de "stock que entró sin una compra
    detrás" —no aparece en el listado de divisas ni asienta caja al resincronizar—.

    El costo es la cotización que declaró el operador: contra eso se calcula la
    ganancia el día que los venda, igual que si los hubiera comprado."""
    if not pasivo.ingreso_caja or pasivo.moneda != Moneda.USD:
        return None
    lote = MovimientoEfectivo(
        tipo=MovimientoEfectivoTipo.COMPRA,
        moneda=Moneda.USD,
        monto=pasivo.monto,
        cotizacion_aplicada=pasivo.cotizacion_ingreso_usd,
        ganancia=_CERO,
        usd_restante=pasivo.monto,  # lote intacto: nada consumido todavía
        fecha_operacion=datetime.combine(
            pasivo.fecha_ingreso or hoy_local(), time.min, tzinfo=UTC
        ),
        observaciones=f"Stock por préstamo recibido de {pasivo.acreedor}",
        es_ajuste=True,
    )
    db.add(lote)
    db.flush()
    pasivo.lote_id = lote.id
    return lote


def _borrar_lote_usd(db: Session, pasivo: Pasivo) -> None:
    """Saca de la cadena el lote de un préstamo en dólares (sin commit).

    Se bloquea si ya se vendió algo de ese lote: quitarlo dejaría esas ventas sin
    el stock del que salieron y reescribiría su ganancia ya reportada. Mismo
    criterio que anular un ajuste en USD (§Ajustes de caja)."""
    if pasivo.lote_id is None:
        return
    lote = db.get(MovimientoEfectivo, pasivo.lote_id)
    # Se valida ANTES de tocar nada: si esto corta a mitad de camino, la deuda no
    # puede quedar sin su vínculo al lote que sigue existiendo.
    if lote is not None and lote.usd_restante != lote.monto:
        consumido = lote.monto - lote.usd_restante
        raise ConflictError(
            f"No se puede cambiar esta deuda: {consumido} de los {lote.monto} USD que "
            "te prestaron ya se vendieron. Anulá primero esas ventas."
        )
    pasivo.lote_id = None
    if lote is not None:
        db.delete(lote)


def _registrar_ingreso(
    db: Session, pasivo: Pasivo, medio: MedioPago = MedioPago.EFECTIVO
) -> None:
    """Asienta (sin commit) el ingreso de la plata que se tomó prestada.

    No hace nada si la deuda no trajo plata, que es el caso normal. `medio` dice
    por dónde entró: quien te presta suele transferir, pero el default sigue el
    resto del sistema y es el operador quien lo dice (§Caja paralela).

    Tampoco asienta nada si el ingreso es anterior al corte: esa plata entró
    antes de la línea y el saldo de arranque ya la tiene adentro (§Reset de
    caja)."""
    if not pasivo.ingreso_caja:
        return
    fecha_ingreso = pasivo.fecha_ingreso or hoy_local()
    if svc_apertura.es_anterior_al_corte(db, fecha_ingreso):
        return
    svc_caja.registrar(
        db,
        fecha=fecha_ingreso,
        moneda=pasivo.moneda,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.INGRESO_PASIVO,
        monto=pasivo.monto,
        medio_pago=medio,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=f"Préstamo recibido de {pasivo.acreedor} — {pasivo.concepto}",
    )


def _resync_caja_ingreso(db: Session, pasivo: Pasivo) -> None:
    """Rehace la línea de caja del alta tras editar la deuda (sin commit).

    Barre **solo** la línea `INGRESO_PASIVO`: los `PAGO_PASIVO` de la misma
    referencia son plata que salió de verdad y no se tocan.

    Si el préstamo era en dólares, rehace también su lote de stock: el monto, la
    moneda y la fecha son tanto la línea de caja como el lote."""
    medio = svc_caja.medio_de_referencia(
        db, "pasivo", pasivo.id, CajaCategoria.INGRESO_PASIVO
    )
    svc_caja.borrar_por_referencia(
        db, "pasivo", pasivo.id, categoria=CajaCategoria.INGRESO_PASIVO
    )
    _registrar_ingreso(db, pasivo, medio)

    # El lote se rehace siempre que había uno o corresponde uno nuevo. Borrar antes
    # de crear: la deuda es una sola y corregirla no debe acumular lotes.
    tenia_lote = pasivo.lote_id is not None
    _borrar_lote_usd(db, pasivo)
    creado = _crear_lote_usd(db, pasivo)
    if tenia_lote or creado is not None:
        # El stock cambió: hay que reimputar la cadena, o las ventas posteriores
        # quedarían apuntando a un lote que ya no existe.
        from app.services.movimientos import _reimputar_fifo

        db.flush()
        _reimputar_fifo(db)


def get_pasivo(db: Session, pasivo_id: uuid.UUID) -> Pasivo:
    pasivo = db.get(Pasivo, pasivo_id)
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    return pasivo


# ══════════════════════════════════════════════════════════════════════
#  Compras a deber: el pasivo que genera la propia compra
# ══════════════════════════════════════════════════════════════════════

def repartir_compra(
    total: Decimal, monto_abonado: Decimal | None
) -> tuple[Decimal, Decimal]:
    """Parte el precio de una compra en (lo que salió de la caja, lo que se debe).

    `monto_abonado` en `None` significa **se pagó todo**: es la compra normal y el
    comportamiento que el sistema tuvo siempre, así que un default distinto
    cambiaría en silencio la caja de todas las compras existentes.

    Pura (sin BD): la comparten la compra de dólares y la de cheques, que solo
    difieren en cómo calculan el total —`monto × cotización` contra el valor neto
    del cheque— y tienen que repartirlo igual."""
    total = total.quantize(Decimal("0.01"))
    if monto_abonado is None:
        return total, _CERO
    abonado = monto_abonado.quantize(Decimal("0.01"))
    if abonado < _CERO:
        raise ValidationError("El monto abonado no puede ser negativo.")
    if abonado > total:
        raise ValidationError(
            f"Abonaste ${abonado} y la compra es de ${total}: el monto abonado no "
            "puede superar el total."
        )
    return abonado, (total - abonado).quantize(Decimal("0.01"))


def crear_por_compra(
    db: Session,
    *,
    acreedor: str,
    concepto: str,
    monto: Decimal,
    moneda: Moneda,
    origen_tipo: str,
    origen_id: uuid.UUID,
    fecha_vencimiento: date | None = None,
) -> Pasivo:
    """Asienta lo que quedó a deber de una compra (dólares o cheque).

    **No commitea**: la persiste el commit de la propia compra, para que la
    compra y su deuda entren o no entren juntas. Es el mismo criterio con el que
    `caja.registrar` asienta el libro.

    No mueve la caja —esa es toda la gracia de comprar a deber: la plata no
    salió—. El egreso lo asienta la compra por lo que sí se abonó, y el resto
    aparecerá el día que se pague este pasivo (o nunca, si se salda compensándolo
    contra un cliente que debe)."""
    pasivo = Pasivo(
        acreedor=acreedor.strip(),
        concepto=concepto.strip(),
        monto=monto,
        saldo_pendiente=monto,
        moneda=moneda,
        estado=PasivoEstado.PENDIENTE,
        fecha_vencimiento=fecha_vencimiento,
        origen_tipo=origen_tipo,
        origen_id=origen_id,
    )
    db.add(pasivo)
    return pasivo


def pasivo_de_origen(
    db: Session, origen_tipo: str, origen_id: uuid.UUID
) -> Pasivo | None:
    """El pasivo vivo que generó una compra, si quedó algo a deber."""
    return db.scalar(
        select(Pasivo).where(
            Pasivo.origen_tipo == origen_tipo,
            Pasivo.origen_id == origen_id,
            Pasivo.anulado_at.is_(None),
        )
    )


def list_pasivos(db: Session, estado: PasivoEstado | None = None) -> list[Pasivo]:
    stmt = select(Pasivo).where(Pasivo.anulado_at.is_(None))
    if estado is not None:
        stmt = stmt.where(Pasivo.estado == estado)
    stmt = stmt.order_by(Pasivo.fecha_vencimiento.asc().nulls_last(), Pasivo.created_at.desc())
    return list(db.scalars(stmt).all())


def editar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoUpdate
) -> Pasivo:
    """Corrige la carga de una deuda (panel).

    `acreedor`, `concepto`, `fecha_vencimiento` y `observaciones` se editan siempre.
    `monto`/`moneda` solo si la deuda está PENDIENTE y sin pagos parciales (cambiarlos
    con pagos hechos desincronizaría la caja); al editar el monto se recalcula el saldo.

    `ingreso_caja`/`fecha_ingreso` corrigen si con la deuda entró plata y qué día:
    sirve tanto para marcar un préstamo que se cargó como deuda común (el ingreso
    aparece) como para desmarcarlo (el ingreso desaparece). Como el monto, la moneda
    y el acreedor son parte de esa línea, cualquiera de ellos la manda a rehacer."""
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")

    data = payload.model_dump(exclude_unset=True)
    cambia_dinero = "monto" in data or "moneda" in data
    tiene_pagos = pasivo.saldo_pendiente != pasivo.monto
    if cambia_dinero and (pasivo.estado == PasivoEstado.CANCELADA or tiene_pagos):
        raise ConflictError(
            "La deuda está cancelada o ya tiene pagos parciales; solo se pueden editar "
            "acreedor, concepto, vencimiento y observaciones."
        )

    if "acreedor" in data:
        pasivo.acreedor = data["acreedor"].strip()
    if "concepto" in data:
        pasivo.concepto = data["concepto"].strip()
    if "fecha_vencimiento" in data:
        pasivo.fecha_vencimiento = data["fecha_vencimiento"]
    if "observaciones" in data:
        pasivo.observaciones = data["observaciones"]
    if "moneda" in data:
        pasivo.moneda = data["moneda"]
    if "monto" in data:
        # Sin pagos parciales (garantizado arriba): el saldo sigue al monto.
        pasivo.monto = data["monto"]
        pasivo.saldo_pendiente = data["monto"]
    if "fecha_ingreso" in data:
        pasivo.fecha_ingreso = data["fecha_ingreso"]
    if "cotizacion_ingreso_usd" in data:
        pasivo.cotizacion_ingreso_usd = data["cotizacion_ingreso_usd"]
    if "ingreso_caja" in data:
        pasivo.ingreso_caja = data["ingreso_caja"]
        if not pasivo.ingreso_caja:
            pasivo.fecha_ingreso = None
    # Marcar que entró plata sin decir qué día: se imputa al día del alta, que es
    # cuando se cargó la deuda. Mejor eso que dejar la línea sin fecha.
    if pasivo.ingreso_caja and pasivo.fecha_ingreso is None:
        pasivo.fecha_ingreso = fecha_local(pasivo.created_at)
    if pasivo.ingreso_caja:
        _exigir_cotizacion_usd(pasivo.moneda, pasivo.cotizacion_ingreso_usd)
    else:
        # Sin ingreso no hay lote, y un costo colgado sin dólares confunde.
        pasivo.cotizacion_ingreso_usd = None

    # Cualquiera de estos campos forma parte de la línea de caja del alta.
    if not _CAMPOS_INGRESO.isdisjoint(data):
        _resync_caja_ingreso(db, pasivo)

    db.commit()
    db.refresh(pasivo)
    return pasivo


def pagar_pasivo(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoPagoRequest
) -> Pasivo:
    """Paga una deuda (total o parcial) en efectivo o transferencia.

    La caja se descuenta en la moneda efectivamente pagada (`moneda_pago`); el
    saldo de la deuda baja por el equivalente en su propia moneda (vía cotización
    si el pago cruza monedas)."""
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")

    es_cross = payload.moneda_pago != pasivo.moneda
    reduccion = calcular_reduccion_saldo(
        pasivo.moneda,
        pasivo.saldo_pendiente,
        payload.moneda_pago,
        payload.monto_pagado,
        payload.cotizacion,
    )

    pasivo.saldo_pendiente = (pasivo.saldo_pendiente - reduccion).quantize(Decimal("0.01"))
    fecha = payload.fecha_cancelacion or hoy_local()
    if pasivo.saldo_pendiente == Decimal("0.00"):
        pasivo.estado = PasivoEstado.CANCELADA
        pasivo.fecha_cancelacion = fecha

    # La primera cotización cross-moneda queda como default editable para próximos pagos.
    if es_cross and pasivo.cotizacion_pago is None:
        pasivo.cotizacion_pago = payload.cotizacion

    detalle = f"Pago deuda a {pasivo.acreedor}"
    if es_cross:
        detalle += f" ({reduccion} {pasivo.moneda.value} @ {payload.cotizacion})"

    # Pagar la deuda saca dinero de la caja en la moneda efectivamente pagada (incluye parciales).
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=payload.moneda_pago,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.PAGO_PASIVO,
        monto=payload.monto_pagado,
        referencia_tipo="pasivo",
        referencia_id=pasivo.id,
        detalle=detalle,
        medio_pago=payload.medio_pago,
        cotizacion=payload.cotizacion if es_cross else None,
    )

    if payload.moneda_pago == Moneda.USD:
        # Pagar en dólares los entrega: salen del stock vendible igual que salen
        # de la caja (§Stock de dólares). Cada pago parcial es su propia salida,
        # por eso se agrega sin barrer las anteriores.
        from app.services import stock_usd as svc_stock
        from app.services.movimientos import _reimputar_fifo

        svc_stock.egresar(
            db,
            monto=payload.monto_pagado,
            fecha=fecha,
            origen_tipo="pasivo_pago",
            origen_id=pasivo.id,
            detalle=f"Dólares entregados — {detalle}",
        )
        db.flush()
        _reimputar_fifo(db)

    db.commit()
    db.refresh(pasivo)
    return pasivo


def cancelar_con_cheque(
    db: Session, pasivo_id: uuid.UUID, payload: PasivoCancelarConChequeRequest
) -> Pasivo:
    pasivo = db.scalar(select(Pasivo).where(Pasivo.id == pasivo_id).with_for_update())
    if pasivo is None:
        raise NotFoundError(f"Pasivo {pasivo_id} no encontrado.")
    if pasivo.estado == PasivoEstado.CANCELADA:
        raise ConflictError("El pasivo ya está cancelado.")

    cheque = db.scalar(
        select(Cheque).where(Cheque.id == payload.cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError(f"Cheque '{payload.cheque_id}' no encontrado.")
    if cheque.estado != ChequeEstado.EN_CARTERA:
        raise ConflictError(
            f"El cheque Nº {cheque.nro_cheque} no está en cartera "
            f"(estado: {cheque.estado.value})."
        )

    valor_neto = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    # diferencia > 0: el cheque cubre de más | diferencia < 0: saldo restante
    diferencia = (valor_neto - pasivo.saldo_pendiente).quantize(Decimal("0.01"))

    # Si el cheque cubre de más, el operador DEBE indicar qué hacer con el vuelto.
    if diferencia > Decimal("0.00") and payload.vuelto_modo is None:
        raise ValidationError(
            "El cheque cubre de más. Indicá qué hacer con el vuelto: "
            "'SALDAR_EFECTIVO' (le pagás la diferencia) o 'QUEDA_DEBIENDO' "
            "(queda como deuda a favor del cliente)."
        )

    fecha_canc = payload.fecha_cancelacion or hoy_local()
    try:
        # Pagar la deuda entregando un cheque de cartera NO mueve efectivo (el desembolso
        # ya ocurrió al comprar el cheque); por eso pasa por el modelo, no por svc_cheques.
        cheque.transition_to(
            ChequeEstado.VENDIDO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
        )
        if diferencia >= Decimal("0.00"):
            pasivo.saldo_pendiente = Decimal("0.00")
            pasivo.estado = PasivoEstado.CANCELADA
            pasivo.fecha_cancelacion = fecha_canc
            if diferencia > Decimal("0.00"):
                aplicar_vuelto_cheque(db, cheque, payload.vuelto_modo, diferencia, fecha_canc)
        else:
            pasivo.saldo_pendiente = (-diferencia).quantize(Decimal("0.01"))

        db.commit()
        db.refresh(pasivo)
        return pasivo
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cancelar la deuda con cheque.") from exc


def aplicar_vuelto_cheque(
    db: Session,
    cheque: Cheque,
    modo: str | None,
    diferencia: Decimal,
    fecha: date,
    medio: MedioPago = MedioPago.EFECTIVO,
) -> None:
    """Resuelve el vuelto cuando un cheque cubre de más (diferencia > 0).

    El vuelto es en ARS (el cheque es un instrumento en pesos).

    La usan los dos lados del negocio: pagar un pasivo con un cheque de más
    (§5) y cobrarle a un cliente con un cheque que supera todo lo que debe
    (§2.b). Es la misma situación —el cheque no se puede recortar a medida— y
    tiene que resolverse igual en ambos, por eso vive acá y es pública."""
    cliente = cheque.cliente_origen
    cliente_nombre = cliente.nombre if cliente else "cliente"

    if modo == "SALDAR_EFECTIVO":
        # Le pagás el vuelto en efectivo/transferencia: egreso de caja ARS.
        svc_caja.registrar(
            db,
            fecha=fecha,
            moneda=Moneda.ARS,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.VUELTO_PASIVO,
            monto=diferencia,
            medio_pago=medio,
            referencia_tipo="cheque",
            referencia_id=cheque.id,
            detalle=f"Vuelto en efectivo a {cliente_nombre} (cheque Nº {cheque.nro_cheque})",
        )
    else:  # QUEDA_DEBIENDO
        # Quedás debiendo: se crea un pasivo a favor del cliente (sin movimiento de caja).
        db.add(
            Pasivo(
                acreedor=cliente_nombre,
                concepto=f"Vuelto cheque Nº {cheque.nro_cheque}",
                monto=diferencia,
                saldo_pendiente=diferencia,
                moneda=Moneda.ARS,
                estado=PasivoEstado.PENDIENTE,
            )
        )


# ────────────────────────────────────────────────────────────────────────────
# Pago por acreedor (lo que usa el bot)
# ────────────────────────────────────────────────────────────────────────────
#
# El panel paga una deuda puntual: el operador la ve en pantalla y la clickea,
# así que manda el `pasivo_id`. Por WhatsApp no hay pantalla — el operador dice
# un nombre ("le pagué 500 lucas a Cuello") y puede haberle quedado debiendo
# tres veces. Estas dos funciones son la puerta por nombre: juntan las deudas
# vivas con ese acreedor y reparten el pago de la más vieja a la más nueva,
# igual que la compensación (§2.c).
#
# Por qué no es un `for` llamando a `pagar_pasivo`: esa función commitea. Con
# tres deudas serían tres commits, y si el segundo falla el primero ya quedó
# grabado — la deuda baja a medias y la caja del día queda con un egreso
# huérfano. Acá el reparto entero es una sola transacción.


@dataclass
class PasivoImputado:
    """Cuánto se le aplicó a una deuda concreta del acreedor."""

    pasivo: Pasivo
    imputado: Decimal   # en la moneda de la deuda
    cancelo: bool


@dataclass
class PagoAcreedorResult:
    acreedor: str
    imputaciones: list[PasivoImputado]
    saldo_restante: Decimal   # lo que le seguís debiendo en esa moneda
    cancelados: int


def cargar_pasivos_acreedor(
    db: Session, acreedor: str, moneda: Moneda, *, bloquear: bool = False
) -> list[Pasivo]:
    """Las deudas vivas del negocio con un acreedor, de la más vieja a la más nueva.

    El orden es por `created_at`: un pasivo no tiene fecha de origen propia más
    allá de cuándo se cargó, y el vencimiento no sirve para esto —una deuda que
    vence antes no es más vieja—. Es el mismo criterio de "primero lo más viejo"
    que usa la imputación del lado del cliente (§2.c).

    El match del nombre es **exacto** (case-insensitive): quién resuelve un
    nombre parcial es quien llama —el bot, con su desambiguación— y acá elegir
    de más significaría saldarle la deuda a otro.
    """
    stmt = (
        select(Pasivo)
        .where(
            func.lower(Pasivo.acreedor) == acreedor.strip().lower(),
            Pasivo.moneda == moneda,
            Pasivo.estado == PasivoEstado.PENDIENTE,
            Pasivo.saldo_pendiente > _CERO,
            Pasivo.anulado_at.is_(None),
        )
        .order_by(Pasivo.created_at.asc())
    )
    if bloquear:
        stmt = stmt.with_for_update()
    return list(db.scalars(stmt))


def _repartir_en_moneda_pago(
    imputados: list[Decimal], reduccion_total: Decimal, monto_pagado: Decimal
) -> list[Decimal]:
    """Parte `monto_pagado` en proporción a lo que se imputó a cada deuda.

    Cada deuda lleva su propia línea de caja (así la anulación de un pasivo se
    lleva solo su parte, §Anulación), y esa línea va en la moneda con la que se
    pagó. Cuando el pago cruza monedas, las partes no coinciden con lo imputado
    y hay que prorratear.

    El último renglón se calcula por diferencia en vez de por proporción: así la
    suma de las partes da **exactamente** `monto_pagado` y la caja del día no
    queda corta por un centavo de redondeo.
    """
    if reduccion_total <= _CERO:
        return [_CERO for _ in imputados]

    partes: list[Decimal] = []
    asignado = _CERO
    ultimo = len(imputados) - 1
    for i, imputado in enumerate(imputados):
        if i == ultimo:
            parte = (monto_pagado - asignado).quantize(_CENTAVO)
        else:
            parte = (monto_pagado * imputado / reduccion_total).quantize(_CENTAVO)
        partes.append(parte)
        asignado = (asignado + parte).quantize(_CENTAVO)
    return partes


def pagar_a_acreedor(
    db: Session,
    *,
    acreedor: str,
    moneda_deuda: Moneda,
    monto_pagado: Decimal,
    moneda_pago: Moneda,
    medio_pago: MedioPago,
    cotizacion: Decimal | None = None,
    fecha: date | None = None,
) -> PagoAcreedorResult:
    """Paga con dinero (efectivo o transferencia) las deudas vivas con un acreedor.

    `monto_pagado` es lo que sale de caja, en `moneda_pago`; el saldo de las
    deudas baja por el equivalente en `moneda_deuda` (vía `cotizacion` si el pago
    cruza monedas). Se reparte de la deuda más vieja a la más nueva.

    **Pagar de más no se acomoda solo**: si el pago supera todo lo que le debés,
    la operación falla en vez de dejar un saldo a favor. Por WhatsApp el monto
    viene dictado, y de más suele ser un dedazo o el acreedor equivocado; un
    pasivo a favor inventado hay que ir a borrarlo a mano después (decisión del
    dueño, 2026-08-24). `calcular_reduccion_saldo` tolera un centavo de redondeo
    para que pagar "el total" justo cancele en vez de fallar.
    """
    acreedor = acreedor.strip()
    pasivos = cargar_pasivos_acreedor(db, acreedor, moneda_deuda, bloquear=True)
    if not pasivos:
        raise NotFoundError(
            f"No hay deudas pendientes con '{acreedor}' en {moneda_deuda.value}."
        )

    total = sum((p.saldo_pendiente for p in pasivos), _CERO).quantize(_CENTAVO)
    # Valida la cotización cross-moneda y que el pago no supere el total.
    reduccion = min(
        calcular_reduccion_saldo(
            moneda_deuda, total, moneda_pago, monto_pagado, cotizacion
        ),
        total,
    ).quantize(_CENTAVO)
    if reduccion <= _CERO:
        # Un importe que redondeado a centavos no baja nada —o una cotización que
        # lo pulveriza— no es un pago: se rechaza en vez de contestar "listo" sin
        # haber tocado la deuda, que es peor que fallar.
        raise ValidationError(
            f"Ese importe no alcanza a bajar ni un centavo de la deuda con "
            f"{pasivos[0].acreedor}. Revisá el monto."
        )

    es_cross = moneda_pago != moneda_deuda
    fecha = fecha or hoy_local()

    reparto = repartir_pago_en_cuotas([p.saldo_pendiente for p in pasivos], reduccion)
    partes_caja = _repartir_en_moneda_pago(reparto, reduccion, monto_pagado)

    imputaciones: list[PasivoImputado] = []
    cancelados = 0
    for pasivo, imputa, parte in zip(pasivos, reparto, partes_caja):
        if imputa <= _CERO:
            continue
        pasivo.saldo_pendiente = (pasivo.saldo_pendiente - imputa).quantize(_CENTAVO)
        cancelo = pasivo.saldo_pendiente <= _CERO
        if cancelo:
            pasivo.saldo_pendiente = _CERO
            pasivo.estado = PasivoEstado.CANCELADA
            pasivo.fecha_cancelacion = fecha
            cancelados += 1
        # La primera cotización cross-moneda queda como default editable, igual
        # que en el pago del panel (§5).
        if es_cross and pasivo.cotizacion_pago is None:
            pasivo.cotizacion_pago = cotizacion

        detalle = f"Pago deuda a {pasivo.acreedor}"
        if es_cross:
            detalle += f" ({imputa} {moneda_deuda.value} @ {cotizacion})"
        # Una línea de caja **por deuda**: anular un pasivo barre la caja por su
        # `referencia_id`, así que una sola línea contra el primero se llevaría
        # también lo que se pagó de los otros (§Anulación).
        svc_caja.registrar(
            db,
            fecha=fecha,
            moneda=moneda_pago,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.PAGO_PASIVO,
            monto=parte,
            referencia_tipo="pasivo",
            referencia_id=pasivo.id,
            detalle=detalle,
            medio_pago=medio_pago,
            cotizacion=cotizacion if es_cross else None,
        )

        if moneda_pago == Moneda.USD:
            # Pagar en dólares los entrega: salen del stock vendible igual que
            # salen de la caja (§Stock de dólares).
            from app.services import stock_usd as svc_stock

            svc_stock.egresar(
                db,
                monto=parte,
                fecha=fecha,
                origen_tipo="pasivo_pago",
                origen_id=pasivo.id,
                detalle=f"Dólares entregados — {detalle}",
            )

        imputaciones.append(PasivoImputado(pasivo=pasivo, imputado=imputa, cancelo=cancelo))

    if moneda_pago == Moneda.USD:
        from app.services.movimientos import _reimputar_fifo

        db.flush()
        _reimputar_fifo(db)

    db.commit()
    restante = (total - reduccion).quantize(_CENTAVO)
    for imp in imputaciones:
        db.refresh(imp.pasivo)
    return PagoAcreedorResult(
        acreedor=pasivos[0].acreedor,
        imputaciones=imputaciones,
        saldo_restante=restante,
        cancelados=cancelados,
    )


def cancelar_a_acreedor_con_cheque(
    db: Session,
    *,
    acreedor: str,
    cheque: Cheque,
    porcentaje_venta: Decimal,
    operador_id: str,
    motivo: str,
    fecha: date | None = None,
) -> PagoAcreedorResult:
    """Entrega un cheque de cartera para saldar deudas con un acreedor.

    El cheque vale su **neto** (nominal menos el porcentaje pactado) y con eso se
    van llenando las deudas de la más vieja a la más nueva. No mueve efectivo: el
    desembolso ya ocurrió cuando se compró el cheque, así que solo cambia de manos
    el papel (§5).

    Las deudas son las **en pesos**: un cheque es un instrumento en ARS y no hay
    con qué convertirlo sin una cotización que nadie dictó.

    **Si el cheque cubre de más, no se entrega**: el vuelto del panel deja elegir
    entre pagar la diferencia o quedar debiendo, y por WhatsApp esa elección no
    está — inventar una de las dos mueve plata o crea una deuda que el operador
    no pidió. Se avisa y se resuelve en el panel (decisión del dueño, 2026-08-24).
    """
    acreedor = acreedor.strip()
    if cheque.estado != ChequeEstado.EN_CARTERA:
        raise ConflictError(
            f"El cheque Nº {cheque.nro_cheque} no está en cartera "
            f"(estado: {cheque.estado.value})."
        )

    pasivos = cargar_pasivos_acreedor(db, acreedor, Moneda.ARS, bloquear=True)
    if not pasivos:
        raise NotFoundError(f"No hay deudas pendientes en pesos con '{acreedor}'.")

    valor_neto = (
        cheque.monto * (Decimal("100") - porcentaje_venta) / Decimal("100")
    ).quantize(_CENTAVO)
    total = sum((p.saldo_pendiente for p in pasivos), _CERO).quantize(_CENTAVO)
    if valor_neto - total > _CENTAVO:
        raise ValidationError(
            f"El cheque Nº {cheque.nro_cheque} vale ${valor_neto} netos y a "
            f"{pasivos[0].acreedor} le debés ${total}: cubre de más. El vuelto "
            "se resuelve desde el panel."
        )

    if valor_neto <= _CERO:
        # Un cheque entregado al 100% no vale nada: saldaría cero y saldría de
        # la cartera igual. Es plata que se pierde sin que nada avise.
        raise ValidationError(
            f"Con ese porcentaje el cheque Nº {cheque.nro_cheque} no vale nada: "
            "revisá el descuento."
        )

    fecha = fecha or hoy_local()
    reduccion = min(valor_neto, total).quantize(_CENTAVO)
    reparto = repartir_pago_en_cuotas([p.saldo_pendiente for p in pasivos], reduccion)

    try:
        # Entregar el cheque lo saca de cartera. Pasa por el modelo y no por
        # svc_cheques porque esta venta no cobra efectivo: el papel se va a
        # cambio de una deuda, no de plata (§5).
        cheque.transition_to(
            ChequeEstado.VENDIDO,
            operador_id=operador_id,
            motivo=motivo,
            porcentaje_venta=porcentaje_venta,
        )

        imputaciones: list[PasivoImputado] = []
        cancelados = 0
        for pasivo, imputa in zip(pasivos, reparto):
            if imputa <= _CERO:
                continue
            pasivo.saldo_pendiente = (pasivo.saldo_pendiente - imputa).quantize(_CENTAVO)
            cancelo = pasivo.saldo_pendiente <= _CERO
            if cancelo:
                pasivo.saldo_pendiente = _CERO
                pasivo.estado = PasivoEstado.CANCELADA
                pasivo.fecha_cancelacion = fecha
                cancelados += 1
            imputaciones.append(
                PasivoImputado(pasivo=pasivo, imputado=imputa, cancelo=cancelo)
            )

        db.commit()
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo pagar la deuda con el cheque.") from exc

    for imp in imputaciones:
        db.refresh(imp.pasivo)
    return PagoAcreedorResult(
        acreedor=pasivos[0].acreedor,
        imputaciones=imputaciones,
        saldo_restante=(total - reduccion).quantize(_CENTAVO),
        cancelados=cancelados,
    )
