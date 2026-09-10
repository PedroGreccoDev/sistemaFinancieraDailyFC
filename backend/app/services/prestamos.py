from __future__ import annotations

import calendar
import logging
import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Cliente,
    Cuota,
    CuotaEstado,
    FrecuenciaCuotas,
    MedioPago,
    Moneda,
    Prestamo,
    PrestamoEstado,
    PrestamoTipo,
)
from app.core.fechas import hoy_local
from app.schemas.prestamos import (
    AbonarCapitalRequest,
    CancelarInteresFijoRequest,
    CobrarInteresRequest,
    CuotaCobrarConChequeRequest,
    CuotasLoteCobrarConChequeRequest,
    InteresFijoUpdate,
    PrestamoCreate,
    PrestamoPagoRequest,
    PrestamoUpdate,
)
from app.services import apertura as svc_apertura
from app.services import caja as svc_caja
from app.services import stock_usd as svc_stock
from app.services.conversion import calcular_reduccion_saldo
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

logger = logging.getLogger(__name__)


def _reimputar_stock(db: Session) -> None:
    """Recalcula la cadena FIFO tras mover stock (sin commit).

    El SELECT de la reimputación no vería lo recién agregado o borrado: la sesión
    va con `autoflush=False`."""
    db.flush()
    from app.services.movimientos import _reimputar_fifo

    _reimputar_fifo(db)


def _resync_stock_otorgamiento(db: Session, prestamo: Prestamo) -> None:
    """Rehace la salida de stock de un préstamo otorgado en dólares (sin commit).

    Prestar dólares los entrega: salen del stock vendible igual que salen de la
    caja (§Stock de dólares). Se barre siempre —aunque el préstamo sea en pesos—
    porque una carga corregida de USD a ARS tiene que devolver los dólares que
    había consumido."""
    tenia = svc_stock.listar_por_origen(db, "prestamo", prestamo.id)
    if not tenia and prestamo.moneda != Moneda.USD:
        return

    svc_stock.borrar_por_origen(db, "prestamo", prestamo.id)
    if prestamo.moneda == Moneda.USD:
        cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
        svc_stock.egresar(
            db,
            monto=prestamo.credito,
            fecha=prestamo.fecha_inicio,
            origen_tipo="prestamo",
            origen_id=prestamo.id,
            detalle=f"Dólares prestados a {cliente_nombre}",
        )
    _reimputar_stock(db)


def _ingresar_stock_cobro(
    db: Session,
    prestamo: Prestamo,
    *,
    monto: Decimal,
    moneda_pago: Moneda,
    cotizacion_stock: Decimal | None,
    fecha: date,
    detalle: str,
) -> None:
    """Mete al stock los dólares que entraron por un cobro (sin commit).

    Cobrar en USD hace entrar dólares: si no entran al stock con su costo, no se
    van a poder vender (§Stock de dólares). La cotización la declara el operador y
    nunca se asume."""
    if moneda_pago != Moneda.USD or monto <= Decimal("0.00"):
        return
    svc_stock.ingresar(
        db,
        monto=monto,
        cotizacion=cotizacion_stock,
        fecha=fecha,
        origen_tipo="prestamo_cobro",
        origen_id=prestamo.id,
        detalle=detalle,
    )
    _reimputar_stock(db)


def _etiqueta_cuota(prestamo: Prestamo, cuota: Cuota) -> str:
    """Cómo se nombra la cuota en el libro de caja, según la modalidad.

    En un préstamo a interés fijo la cuota no es una porción del cuadro: es el
    interés de un período de 30 días. Llamarla "Cuota #3" en el reporte diario
    haría pensar que quedan cuotas por delante, y no hay cuadro que terminar."""
    if prestamo.tipo_prestamo == PrestamoTipo.INTERES_FIJO:
        return f"Interés período #{cuota.numero_cuota}"
    return f"Cuota #{cuota.numero_cuota}"


def _registrar_cobro_cuota(
    db: Session,
    prestamo: Prestamo,
    cuota: Cuota,
    monto: Decimal,
    medio_pago: MedioPago,
    cotizacion_stock: Decimal | None = None,
) -> None:
    """Asienta en la caja el ingreso por lo cobrado de una cuota (en la moneda del préstamo).

    `monto` es lo efectivamente cobrado ahora: para una cuota entera es su `monto`,
    pero si venía con un pago parcial previo es solo el restante. No asienta nada si
    `monto` no es positivo (la caja rechaza montos ≤ 0)."""
    if monto <= Decimal("0.00"):
        return
    cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
    etiqueta = _etiqueta_cuota(prestamo, cuota)
    svc_caja.registrar(
        db,
        fecha=cuota.fecha_cobro,
        moneda=prestamo.moneda,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_CUOTA,
        monto=monto,
        medio_pago=medio_pago,
        referencia_tipo="cuota",
        referencia_id=cuota.id,
        detalle=f"{etiqueta} - {cliente_nombre}",
    )
    _ingresar_stock_cobro(
        db,
        prestamo,
        monto=monto,
        moneda_pago=prestamo.moneda,
        cotizacion_stock=cotizacion_stock,
        fecha=cuota.fecha_cobro,
        detalle=f"Stock por {etiqueta.lower()} - {cliente_nombre}",
    )


def _add_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def calcular_vencimiento(fecha_inicio: date, frecuencia: FrecuenciaCuotas, numero: int) -> date:
    if frecuencia == FrecuenciaCuotas.DIARIA:
        return fecha_inicio + timedelta(days=numero)
    if frecuencia == FrecuenciaCuotas.SEMANAL:
        return fecha_inicio + timedelta(weeks=numero)
    if frecuencia == FrecuenciaCuotas.QUINCENAL:
        return fecha_inicio + timedelta(days=15 * numero)
    if frecuencia == FrecuenciaCuotas.MENSUAL:
        return _add_months(fecha_inicio, numero)
    if frecuencia == FrecuenciaCuotas.ANUAL:
        return _add_months(fecha_inicio, 12 * numero)
    if frecuencia == FrecuenciaCuotas.CADA_30_DIAS:
        return fecha_inicio + timedelta(days=CICLO_DIAS * numero)
    raise ValueError(f"Frecuencia no soportada: {frecuencia}")


def construir_cuotas(
    *,
    prestamo: Prestamo,
    fecha_inicio: date,
    cantidad: int,
    frecuencia: FrecuenciaCuotas,
    total_a_cobrar: Decimal,
) -> list[Cuota]:
    monto_base = (total_a_cobrar / Decimal(cantidad)).quantize(Decimal("0.01"))
    cuotas: list[Cuota] = []

    for numero in range(1, cantidad + 1):
        monto = (
            total_a_cobrar - (monto_base * Decimal(cantidad - 1))
            if numero == cantidad
            else monto_base
        )
        cuotas.append(
            Cuota(
                prestamo=prestamo,
                numero_cuota=numero,
                fecha_vencimiento=calcular_vencimiento(fecha_inicio, frecuencia, numero),
                monto=monto,
            )
        )

    return cuotas


# ══════════════════════════════════════════════════════════════════════
#  Préstamo a interés fijo (§Interés fijo)
# ══════════════════════════════════════════════════════════════════════
#
# El capital no se amortiza: queda prestado hasta que el cliente lo devuelve, y
# cada 30 días se cobra un interés fijo en plata. De ahí salen las tres reglas
# que gobiernan todo lo que sigue:
#
#   1. **El período se debe al empezar, no al terminar** (sin prorrateo). La
#      cuota del período k se crea el día en que el período arranca; si el
#      cliente cancela al día siguiente, ese interés se cobra igual.
#   2. **Los períodos se devengan de a uno.** No hay cuadro que pre-generar
#      porque no se sabe cuántos van a ser. `devengar_periodos` crea los que ya
#      arrancaron y todavía no existían, y lo llama toda lectura y toda
#      operación: así el sistema queda al día sin depender de ningún cron.
#   3. **La mora se acumula, no reemplaza.** El interés impago de un período
#      pasa a EN_MORA y el del siguiente se suma. El "período vigente" es
#      siempre el último devengado; todos los anteriores impagos son mora.


CICLO_DIAS = 30

_CERO = Decimal("0.00")


def fecha_de_periodo(dia_cobro: date, numero: int) -> date:
    """Día en que arranca —y se cobra— el período `numero` (1 es el primero).

    Pura (sin BD): testeable en el estilo de `tests/`."""
    if numero < 1:
        raise ValueError("El número de período arranca en 1.")
    return dia_cobro + timedelta(days=CICLO_DIAS * (numero - 1))


def periodos_cumplidos(dia_cobro: date, hasta: date) -> int:
    """Cuántos períodos ya arrancaron al día `hasta`.

    0 mientras no llegue la primera fecha de cobro: el préstamo existe y el
    capital está afuera, pero todavía no se devengó interés. Pura (sin BD)."""
    if hasta < dia_cobro:
        return 0
    return (hasta - dia_cobro).days // CICLO_DIAS + 1


def es_interes_fijo(prestamo: Prestamo) -> bool:
    return prestamo.tipo_prestamo == PrestamoTipo.INTERES_FIJO


def _exigir_interes_fijo(prestamo: Prestamo) -> None:
    if not es_interes_fijo(prestamo):
        raise ConflictError(
            "Esta operación es solo para préstamos a interés fijo. "
            "Este préstamo tiene cuadro de cuotas: cobralo por cuota o con un pago libre."
        )


def periodos(prestamo: Prestamo) -> list[Cuota]:
    """Los períodos devengados, del más viejo al más nuevo."""
    return sorted(prestamo.cuotas_detalle, key=lambda c: c.numero_cuota)


def periodo_vigente(prestamo: Prestamo) -> Cuota | None:
    """El último período devengado, esté cobrado o no.

    Es el que entra en una cancelación: el interés del ciclo en curso se debe
    completo aunque el cliente cancele antes de que se cumpla (sin prorrateo)."""
    devengados = periodos(prestamo)
    return devengados[-1] if devengados else None


def periodos_en_mora(prestamo: Prestamo) -> list[Cuota]:
    """Los períodos anteriores al vigente que quedaron sin saldar.

    Se acumulan: el interés nuevo no reemplaza al viejo, se suma."""
    devengados = periodos(prestamo)
    return [c for c in devengados[:-1] if c.estado != CuotaEstado.COBRADA]


def saldo_cuota(cuota: Cuota) -> Decimal:
    return (cuota.monto - (cuota.monto_pagado or _CERO)).quantize(Decimal("0.01"))


def mora_acumulada(prestamo: Prestamo) -> Decimal:
    return sum((saldo_cuota(c) for c in periodos_en_mora(prestamo)), _CERO).quantize(
        Decimal("0.01")
    )


def total_cancelacion(prestamo: Prestamo, *, incluir_mora: bool) -> Decimal:
    """Lo que hay que cobrar para cancelar: capital + interés del período vigente.

    La mora acumulada entra o no según decida el operador: puede saldarse junto
    con la cancelación o quedar para cobrar aparte (decisión del dueño)."""
    vigente = periodo_vigente(prestamo)
    total = prestamo.capital_pendiente or _CERO
    if vigente is not None:
        total += saldo_cuota(vigente)
    if incluir_mora:
        total += mora_acumulada(prestamo)
    return Decimal(total).quantize(Decimal("0.01"))


def proxima_fecha_cobro(prestamo: Prestamo) -> date | None:
    """Cuándo arranca el próximo período que todavía no se devengó."""
    if prestamo.dia_cobro is None:
        return None
    return fecha_de_periodo(prestamo.dia_cobro, len(prestamo.cuotas_detalle) + 1)


def _marcar_mora(prestamo: Prestamo) -> bool:
    """Pone EN_MORA los períodos impagos que ya no son el vigente. Devuelve si cambió algo.

    No se mira la fecha sino la posición: el vigente es el último devengado, y
    que exista uno posterior significa que el ciclo de este ya terminó."""
    cambio = False
    devengados = periodos(prestamo)
    # Se compara por POSICIÓN, no por id: una cuota recién devengada todavía no
    # tiene id —lo asigna el INSERT— y `None == None` daría "vigente" a todas,
    # dejando la mora sin marcar justo en la pasada que la crea.
    for indice, cuota in enumerate(devengados):
        if cuota.estado == CuotaEstado.COBRADA:
            continue
        objetivo = (
            CuotaEstado.PENDIENTE
            if indice == len(devengados) - 1
            else CuotaEstado.EN_MORA
        )
        if cuota.estado != objetivo:
            cuota.estado = objetivo
            cambio = True
    return cambio


def devengar_periodos(db: Session, prestamo: Prestamo, hasta: date | None = None) -> bool:
    """Crea las cuotas de los períodos que ya arrancaron y faltaban (sin commit).

    Devuelve si hubo algún cambio. Es idempotente: llamarla dos veces el mismo
    día no genera nada la segunda vez, y por eso puede colgarse de las lecturas.

    **No devenga si el capital ya se saldó.** El interés se cobra por tener el
    capital afuera; una vez devuelto no nace un período nuevo. El que estuviera
    en curso al momento de devolverlo ya está devengado y se debe igual.
    """
    if not es_interes_fijo(prestamo) or prestamo.anulado_at is not None:
        return False
    if prestamo.dia_cobro is None or prestamo.monto_interes_fijo is None:
        return False
    if (prestamo.capital_pendiente or _CERO) <= _CERO:
        return _marcar_mora(prestamo)

    objetivo = periodos_cumplidos(prestamo.dia_cobro, hasta or hoy_local())
    ya = len(prestamo.cuotas_detalle)
    nuevas: list[Cuota] = []
    for numero in range(ya + 1, objetivo + 1):
        cuota = Cuota(
            prestamo=prestamo,
            numero_cuota=numero,
            fecha_vencimiento=fecha_de_periodo(prestamo.dia_cobro, numero),
            # El interés se congela al devengarse: editarlo después vale para los
            # períodos que vengan, no reescribe lo que ya se debía.
            monto=prestamo.monto_interes_fijo,
        )
        db.add(cuota)
        nuevas.append(cuota)

    if nuevas:
        devengado = sum((c.monto for c in nuevas), _CERO)
        # El total a cobrar de un préstamo a interés fijo no se conoce al alta:
        # se va conociendo. Arranca en el capital y crece con cada interés que
        # nace, y la ganancia es exactamente ese interés devengado.
        prestamo.total_a_cobrar = (prestamo.total_a_cobrar + devengado).quantize(Decimal("0.01"))
        prestamo.ganancia = (prestamo.ganancia + devengado).quantize(Decimal("0.01"))

    cambio_mora = _marcar_mora(prestamo)
    return bool(nuevas) or cambio_mora


def devengar(db: Session, prestamos: list[Prestamo], hasta: date | None = None) -> int:
    """Devenga y **commitea** los préstamos que lo necesiten. Devuelve cuántos tocó.

    La cuelgan las lecturas (`get_prestamo`, `list_prestamos`), que es lo que
    mantiene el sistema al día sin un cron: el panel, el bot y los reportes ven
    siempre los períodos que ya arrancaron. Si la escritura falla, la lectura
    sigue: un período que no se pudo crear se vuelve a intentar en la próxima,
    y romper una consulta por eso sería peor que mostrarla un rato desactualizada.
    """
    tocados = [p for p in prestamos if devengar_periodos(db, p, hasta)]
    if not tocados:
        return 0
    try:
        for tocado in tocados:
            recalcular_estado(tocado)
        db.commit()
    except SQLAlchemyError:
        db.rollback()
        logger.exception("No se pudieron devengar los períodos de interés fijo")
        return 0
    return len(tocados)


def recalcular_estado(prestamo: Prestamo) -> None:
    """Deja el préstamo en ACTIVO o CANCELADO según lo que le quede por cobrar.

    Va después de **todo** cobro. La trampa que tapa es del interés fijo: ahí las
    cuotas son interés, no capital, y darlo por cancelado porque no quedan cuotas
    impagas sacaría del panel un capital que sigue prestado. Al revés también:
    cancelar dejando mora sin saldar mantiene el préstamo vivo, porque esa deuda
    se sigue debiendo y tiene que verse en la cuenta del cliente.

    Cuenta sobre `cuotas_detalle` en memoria y no sobre la BD a propósito: así ve
    los períodos que se acaban de devengar y todavía no se flushearon, y sirve
    igual a los servicios que imputan sin commitear (`imputar_pago`).
    """
    pendientes = sum(
        1 for c in prestamo.cuotas_detalle if c.estado != CuotaEstado.COBRADA
    )
    if es_interes_fijo(prestamo):
        cancelado = pendientes == 0 and (prestamo.capital_pendiente or _CERO) <= _CERO
    else:
        cancelado = pendientes == 0
    if cancelado:
        prestamo.estado = PrestamoEstado.CANCELADO
    elif prestamo.estado == PrestamoEstado.CANCELADO:
        prestamo.estado = PrestamoEstado.ACTIVO


def _prestamo_interes_fijo_bloqueado(db: Session, prestamo_id: uuid.UUID) -> Prestamo:
    """Trae el préstamo con lock, valida que sea a interés fijo y lo pone al día."""
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
        .with_for_update()
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    if prestamo.anulado_at is not None:
        raise ConflictError("El préstamo está anulado.")
    _exigir_interes_fijo(prestamo)
    # Sin esto, cobrar el día que arranca un período nuevo cobraría el anterior:
    # la operación tiene que ver los mismos períodos que ve el panel.
    if devengar_periodos(db, prestamo):
        # El flush le da `id` a las cuotas recién nacidas. Hace falta antes de
        # cobrarlas: la línea de caja las referencia por id, y sin flush entraría
        # con `referencia_id` en NULL — invisible para la anulación, que barre
        # por referencia.
        db.flush()
    return prestamo


def cobrar_interes(
    db: Session, prestamo_id: uuid.UUID, payload: CobrarInteresRequest
) -> Prestamo:
    """Cobra el interés de uno o varios períodos de un préstamo a interés fijo.

    Sin `cuota_ids`, cobra el **período vigente**; con `incluir_mora`, suma
    además todos los períodos viejos impagos. El capital no se toca: para eso
    está `abonar_capital`.
    """
    prestamo = _prestamo_interes_fijo_bloqueado(db, prestamo_id)

    if payload.cuota_ids:
        por_id = {c.id: c for c in prestamo.cuotas_detalle}
        faltantes = [i for i in payload.cuota_ids if i not in por_id]
        if faltantes:
            raise NotFoundError("Uno o más períodos no pertenecen a este préstamo.")
        elegidas = [por_id[i] for i in payload.cuota_ids]
    else:
        vigente = periodo_vigente(prestamo)
        elegidas = [vigente] if vigente is not None else []
        if payload.incluir_mora:
            elegidas = periodos_en_mora(prestamo) + elegidas

    a_cobrar = [c for c in elegidas if saldo_cuota(c) > _CERO]
    if not a_cobrar:
        if not prestamo.cuotas_detalle:
            raise ConflictError(
                "Todavía no se devengó ningún interés: el primer período arranca "
                f"el {prestamo.dia_cobro:%d/%m/%Y}."
            )
        raise ConflictError("No hay interés pendiente para cobrar en este préstamo.")

    fecha = payload.fecha_cobro or hoy_local()
    for cuota in sorted(a_cobrar, key=lambda c: c.numero_cuota):
        restante = saldo_cuota(cuota)
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = fecha
        _registrar_cobro_cuota(
            db, prestamo, cuota, restante, payload.medio_pago, payload.cotizacion_stock
        )

    try:
        recalcular_estado(prestamo)
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro del interés.") from exc


def abonar_capital(
    db: Session, prestamo_id: uuid.UUID, payload: AbonarCapitalRequest
) -> Prestamo:
    """Recibe capital de vuelta: baja `capital_pendiente` y lo asienta en la caja.

    Va en la moneda del préstamo —el capital se devuelve en lo que se prestó— y
    entra como `DEVOLUCION_CAPITAL`, no como cobro: es plata que vuelve, no
    ganancia. Devolver todo el capital **frena el devengo**: no nacen períodos
    nuevos, aunque el interés del período en curso siga debiéndose.
    """
    prestamo = _prestamo_interes_fijo_bloqueado(db, prestamo_id)

    pendiente = prestamo.capital_pendiente or _CERO
    if pendiente <= _CERO:
        raise ConflictError("Este préstamo ya no tiene capital pendiente.")
    monto = Decimal(payload.monto).quantize(Decimal("0.01"))
    if monto > pendiente:
        raise ValidationError(
            f"El abono ({monto}) supera el capital pendiente ({pendiente}). "
            "Si además está cobrando interés, usá 'Cancelar' o cobralo aparte."
        )

    fecha = payload.fecha_cobro or hoy_local()
    prestamo.capital_pendiente = (pendiente - monto).quantize(Decimal("0.01"))
    _registrar_devolucion_capital(
        db, prestamo, monto=monto, fecha=fecha,
        medio_pago=payload.medio_pago, cotizacion_stock=payload.cotizacion_stock,
    )

    try:
        recalcular_estado(prestamo)
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el abono de capital.") from exc


def _registrar_devolucion_capital(
    db: Session,
    prestamo: Prestamo,
    *,
    monto: Decimal,
    fecha: date,
    medio_pago: MedioPago,
    cotizacion_stock: Decimal | None,
) -> None:
    """Asienta (sin commit) el capital que volvió al cajón."""
    if monto <= _CERO:
        return
    cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=prestamo.moneda,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.DEVOLUCION_CAPITAL,
        monto=monto,
        medio_pago=medio_pago,
        referencia_tipo="prestamo",
        referencia_id=prestamo.id,
        detalle=f"Devolución de capital - {cliente_nombre}",
    )
    _ingresar_stock_cobro(
        db,
        prestamo,
        monto=monto,
        moneda_pago=prestamo.moneda,
        cotizacion_stock=cotizacion_stock,
        fecha=fecha,
        detalle=f"Stock por devolución de capital - {cliente_nombre}",
    )


def editar_interes_fijo(
    db: Session, prestamo_id: uuid.UUID, payload: InteresFijoUpdate
) -> Prestamo:
    """Cambia el interés pactado (y, si todavía no arrancó, la fecha de cobro).

    El interés es **editable sin obligación de modificarlo**: se renegocia cuando
    el dueño quiere y mientras no lo toque sigue valiendo el de siempre. El nuevo
    valor rige **de los próximos períodos en adelante**; lo ya devengado quedó
    congelado con el interés que estaba pactado ese día.

    `aplicar_a_periodo_vigente` es la excepción para el caso real de renegociar
    el ciclo en curso. Solo se permite si ese período no recibió ni un peso: con
    un pago encima, cambiarle el monto reescribiría una cuenta ya empezada.
    """
    prestamo = _prestamo_interes_fijo_bloqueado(db, prestamo_id)
    if prestamo.estado == PrestamoEstado.CANCELADO:
        raise ConflictError("El préstamo ya está cancelado.")

    data = payload.model_dump(exclude_unset=True)

    if "dia_cobro" in data and data["dia_cobro"] != prestamo.dia_cobro:
        if prestamo.cuotas_detalle:
            raise ConflictError(
                "La fecha de cobro es el ancla de los ciclos de 30 días y ya hay "
                f"{len(prestamo.cuotas_detalle)} período(s) devengado(s): moverla "
                "correría todas las fechas. Solo se puede cambiar antes del primer período."
            )
        prestamo.dia_cobro = data["dia_cobro"]

    nuevo = data.get("monto_interes_fijo")
    if nuevo is not None:
        nuevo = Decimal(nuevo).quantize(Decimal("0.01"))
        if payload.aplicar_a_periodo_vigente:
            vigente = periodo_vigente(prestamo)
            if vigente is None:
                raise ConflictError("Todavía no hay un período vigente al que aplicarlo.")
            if (vigente.monto_pagado or _CERO) > _CERO:
                raise ConflictError(
                    f"El período #{vigente.numero_cuota} ya tiene un pago imputado; "
                    "no se le puede cambiar el interés. El nuevo valor rige desde el próximo."
                )
            delta = nuevo - vigente.monto
            vigente.monto = nuevo
            prestamo.total_a_cobrar = (prestamo.total_a_cobrar + delta).quantize(Decimal("0.01"))
            prestamo.ganancia = (prestamo.ganancia + delta).quantize(Decimal("0.01"))
        prestamo.monto_interes_fijo = nuevo

    try:
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el interés fijo.") from exc


def cancelar_interes_fijo(
    db: Session, prestamo_id: uuid.UUID, payload: CancelarInteresFijoRequest
) -> Prestamo:
    """Liquida el préstamo: capital pendiente + interés del período vigente.

    El interés del ciclo en curso va **completo**, aunque falten días para que se
    cumpla: sin prorrateo (decisión del dueño). La mora acumulada entra según
    `incluir_mora`; si queda afuera, el préstamo **no** pasa a CANCELADO —esa
    deuda se sigue debiendo y tiene que seguir viéndose en la cuenta del cliente—.
    """
    prestamo = _prestamo_interes_fijo_bloqueado(db, prestamo_id)
    if prestamo.estado == PrestamoEstado.CANCELADO:
        raise ConflictError("El préstamo ya está cancelado.")

    capital = prestamo.capital_pendiente or _CERO
    vigente = periodo_vigente(prestamo)
    a_cobrar = [c for c in ([vigente] if vigente is not None else []) if saldo_cuota(c) > _CERO]
    if payload.incluir_mora:
        a_cobrar = [c for c in periodos_en_mora(prestamo) if saldo_cuota(c) > _CERO] + a_cobrar
    if capital <= _CERO and not a_cobrar:
        raise ConflictError("El préstamo no tiene nada pendiente para cancelar.")

    fecha = payload.fecha_cobro or hoy_local()
    for cuota in sorted(a_cobrar, key=lambda c: c.numero_cuota):
        restante = saldo_cuota(cuota)
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = fecha
        _registrar_cobro_cuota(
            db, prestamo, cuota, restante, payload.medio_pago, payload.cotizacion_stock
        )

    if capital > _CERO:
        prestamo.capital_pendiente = _CERO
        _registrar_devolucion_capital(
            db, prestamo, monto=capital, fecha=fecha,
            medio_pago=payload.medio_pago, cotizacion_stock=payload.cotizacion_stock,
        )

    try:
        recalcular_estado(prestamo)
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cancelar el préstamo.") from exc


def _armar_interes_fijo(payload: PrestamoCreate, fecha_inicio: date) -> Prestamo:
    """Arma el préstamo a interés fijo del alta. Sin cuotas: se devengan solas.

    `total_a_cobrar` arranca igual al capital y `ganancia` en cero porque acá el
    total **no se conoce al alta**: depende de cuántos períodos dure el préstamo,
    y eso lo decide el cliente cuando devuelve el capital. Los dos crecen con
    cada interés que se devenga (`devengar_periodos`).

    Si el operador no fija la fecha de cobro, se toma un ciclo después de la
    entrega: es lo que significa "le presté hoy y me paga el mes que viene".
    """
    dia_cobro = payload.dia_cobro or (fecha_inicio + timedelta(days=CICLO_DIAS))
    return Prestamo(
        cliente_id=payload.cliente_id,
        tipo_prestamo=PrestamoTipo.INTERES_FIJO,
        credito=payload.credito,
        moneda=payload.moneda,
        # 0 no es "cero cuotas": es "no tiene cuadro" (§migración 0031).
        cuotas=0,
        frecuencia=FrecuenciaCuotas.CADA_30_DIAS,
        total_a_cobrar=payload.credito,
        ganancia=_CERO,
        estado=PrestamoEstado.ACTIVO,
        fecha_inicio=fecha_inicio,
        monto_interes_fijo=payload.monto_interes_fijo,
        dia_cobro=dia_cobro,
        capital_pendiente=payload.credito,
    )


# ══════════════════════════════════════════════════════════════════════
#  Alta, lectura y edición (las dos modalidades)
# ══════════════════════════════════════════════════════════════════════

def create_prestamo(db: Session, payload: PrestamoCreate) -> Prestamo:
    cliente = db.get(Cliente, payload.cliente_id)
    if cliente is None:
        raise NotFoundError("Cliente no encontrado.")

    fecha_inicio = payload.fecha_inicio or hoy_local()
    if payload.tipo_prestamo == PrestamoTipo.INTERES_FIJO:
        prestamo = _armar_interes_fijo(payload, fecha_inicio)
    else:
        prestamo = Prestamo(
            cliente_id=payload.cliente_id,
            tipo_prestamo=PrestamoTipo.NORMAL,
            credito=payload.credito,
            moneda=payload.moneda,
            cuotas=payload.cuotas,
            frecuencia=payload.frecuencia,
            total_a_cobrar=payload.total_a_cobrar,
            ganancia=payload.total_a_cobrar - payload.credito,
            estado=PrestamoEstado.ACTIVO,
            fecha_inicio=fecha_inicio,
        )
        prestamo.cuotas_detalle = construir_cuotas(
            prestamo=prestamo,
            fecha_inicio=fecha_inicio,
            cantidad=payload.cuotas,
            frecuencia=payload.frecuencia,
            total_a_cobrar=payload.total_a_cobrar,
        )

    try:
        db.add(prestamo)
        db.flush()
        # Otorgar el préstamo es un egreso de caja: sale el crédito entregado.
        svc_caja.registrar(
            db,
            fecha=fecha_inicio,
            moneda=prestamo.moneda,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.OTORGAMIENTO_PRESTAMO,
            monto=prestamo.credito,
            medio_pago=payload.medio_pago,
            referencia_tipo="prestamo",
            referencia_id=prestamo.id,
            detalle=f"Préstamo a {cliente.nombre}",
        )
        _resync_stock_otorgamiento(db, prestamo)
        db.commit()
        db.refresh(prestamo)
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el prestamo.") from exc


def get_prestamo(db: Session, prestamo_id: uuid.UUID) -> Prestamo:
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    # Toda lectura pone al día los períodos de interés fijo: es lo que reemplaza
    # al cron que no existe (§Interés fijo).
    devengar(db, [prestamo])
    return prestamo


def list_prestamos(db: Session, estado: PrestamoEstado | None = None) -> list[Prestamo]:
    query = (
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.anulado_at.is_(None))
    )
    if estado is not None:
        query = query.where(Prestamo.estado == estado)
    prestamos = list(db.scalars(query.order_by(Prestamo.created_at.desc())))
    # Toda lectura pone al día los períodos de interés fijo (§Interés fijo). El
    # re-filtro es una red: hoy el devengo no puede cambiar el estado de un
    # préstamo —solo agrega cuotas, y eso nunca lo cancela—, pero si algún día
    # pudiera, el listado no debería devolver una fila que ya no corresponde.
    if devengar(db, prestamos) and estado is not None:
        prestamos = [p for p in prestamos if p.estado == estado]
    return prestamos


def editar_prestamo(
    db: Session, prestamo_id: uuid.UUID, payload: PrestamoUpdate
) -> Prestamo:
    """Corrige la carga de un préstamo (panel) regenerando el cuadro de cuotas.

    Solo se permite si el préstamo está ACTIVO y NINGUNA cuota fue cobrada: editar
    capital/total/cantidad/frecuencia/fecha rehace todas las cuotas y el egreso de
    caja del otorgamiento. Si ya hubo cobros, se rechaza (desincronizaría la caja)."""
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
        .with_for_update()
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    if prestamo.estado != PrestamoEstado.ACTIVO:
        raise ConflictError(
            f"El préstamo está {prestamo.estado.value} y no se puede editar."
        )
    if es_interes_fijo(prestamo):
        # Esta edición regenera el cuadro de cuotas, y un préstamo a interés fijo
        # no tiene cuadro: le borraría los períodos ya devengados —con su mora—.
        raise ConflictError(
            "Este préstamo es a interés fijo y no tiene cuadro de cuotas que "
            "regenerar. Para cambiar el interés usá 'Editar interés'."
        )
    if any(c.estado == CuotaEstado.COBRADA for c in prestamo.cuotas_detalle):
        raise ConflictError(
            "El préstamo ya tiene cuotas cobradas; no se puede editar su carga. "
            "Anulá los cobros o creá un préstamo nuevo."
        )

    data = payload.model_dump(exclude_unset=True)
    credito = data.get("credito", prestamo.credito)
    total = data.get("total_a_cobrar", prestamo.total_a_cobrar)
    cantidad = data.get("cuotas", prestamo.cuotas)
    frecuencia = data.get("frecuencia", prestamo.frecuencia)
    moneda = data.get("moneda", prestamo.moneda)
    fecha_inicio = data.get("fecha_inicio", prestamo.fecha_inicio)
    if total < credito:
        raise ValidationError("El total a cobrar debe ser mayor o igual al capital.")

    prestamo.credito = credito
    prestamo.total_a_cobrar = total
    prestamo.cuotas = cantidad
    prestamo.frecuencia = frecuencia
    prestamo.moneda = moneda
    prestamo.fecha_inicio = fecha_inicio
    prestamo.ganancia = total - credito

    # Regenerar el cuadro de cuotas (borra las viejas vía delete-orphan).
    prestamo.cuotas_detalle.clear()
    db.flush()
    prestamo.cuotas_detalle = construir_cuotas(
        prestamo=prestamo,
        fecha_inicio=fecha_inicio,
        cantidad=cantidad,
        frecuencia=frecuencia,
        total_a_cobrar=total,
    )

    try:
        # Rehacer el egreso de caja del otorgamiento (monto/moneda/fecha pueden cambiar).
        # El medio se conserva salvo que la edición traiga otro: corregir el monto
        # de un préstamo entregado por transferencia no debe devolverlo al efectivo.
        medio = data.get("medio_pago") or svc_caja.medio_de_referencia(
            db, "prestamo", prestamo.id, CajaCategoria.OTORGAMIENTO_PRESTAMO
        )
        # Acotado a la categoría del otorgamiento: bajo la referencia `prestamo`
        # también cuelgan los pagos de importe libre (COBRO_CUOTA) y, desde el
        # interés fijo, las devoluciones de capital. Barrer todo borraría plata
        # que entró de verdad.
        svc_caja.borrar_por_referencia(
            db, "prestamo", prestamo.id, CajaCategoria.OTORGAMIENTO_PRESTAMO
        )
        cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
        # Un préstamo anterior al corte ya salió de la caja vieja: reasentarlo
        # restaría esa plata dos veces (§Reset de caja). Se borra la línea igual
        # —si quedó alguna, no corresponde— y no se vuelve a escribir.
        if svc_apertura.es_anterior_al_corte(db, fecha_inicio):
            _resync_stock_otorgamiento(db, prestamo)
            db.commit()
            return get_prestamo(db, prestamo.id)
        svc_caja.registrar(
            db,
            fecha=fecha_inicio,
            moneda=moneda,
            tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.OTORGAMIENTO_PRESTAMO,
            monto=credito,
            medio_pago=medio,
            referencia_tipo="prestamo",
            referencia_id=prestamo.id,
            detalle=f"Préstamo a {cliente_nombre}",
        )
        _resync_stock_otorgamiento(db, prestamo)
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el prestamo.") from exc


def cobrar_cuota(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_id: uuid.UUID,
    fecha_cobro: date | None = None,
    cotizacion_stock: Decimal | None = None,
    medio_pago: MedioPago = MedioPago.EFECTIVO,
) -> Cuota:
    cuota = db.scalar(
        select(Cuota)
        .where(Cuota.id == cuota_id, Cuota.prestamo_id == prestamo_id)
        .with_for_update()
    )
    if cuota is None:
        raise NotFoundError("Cuota no encontrada.")
    if cuota.estado == CuotaEstado.COBRADA:
        raise ConflictError("La cuota ya fue cobrada.")

    # Cobrar la cuota entera salda lo que le falte (puede traer un pago parcial previo).
    restante = (cuota.monto - cuota.monto_pagado).quantize(Decimal("0.01"))
    cuota.monto_pagado = cuota.monto
    cuota.estado = CuotaEstado.COBRADA
    cuota.fecha_cobro = fecha_cobro or hoy_local()

    try:
        db.flush()
        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            _registrar_cobro_cuota(
                db, prestamo, cuota, restante, medio_pago, cotizacion_stock
            )
        # Cualquier cuota no cobrada (PENDIENTE o EN_MORA) mantiene vivo el
        # préstamo — y en el interés fijo, también el capital que falte devolver.
        if prestamo is not None:
            recalcular_estado(prestamo)
        db.commit()
        db.refresh(cuota)
        return cuota
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de la cuota.") from exc


def cobrar_cuota_con_cheque(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_id: uuid.UUID,
    payload: CuotaCobrarConChequeRequest,
) -> tuple[Cuota, Cheque]:
    cuota = db.scalar(
        select(Cuota)
        .where(Cuota.id == cuota_id, Cuota.prestamo_id == prestamo_id)
        .with_for_update()
    )
    if cuota is None:
        raise NotFoundError("Cuota no encontrada.")
    if cuota.estado == CuotaEstado.COBRADA:
        raise ConflictError("La cuota ya fue cobrada.")

    cheque = Cheque(
        nro_cheque=payload.nro_cheque,
        banco=payload.banco,
        monto=payload.monto,
        porcentaje_compra=payload.porcentaje_compra,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        cliente_origen_id=payload.cliente_origen_id,
        estado=ChequeEstado.EN_CARTERA,
    )

    # El cheque entra a cartera y salda la cuota completa (no mueve efectivo en caja).
    cuota.monto_pagado = cuota.monto
    cuota.estado = CuotaEstado.COBRADA
    cuota.fecha_cobro = payload.fecha_cobro or hoy_local()

    try:
        db.add(cheque)
        db.flush()

        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            recalcular_estado(prestamo)

        db.commit()
        db.refresh(cuota)
        db.refresh(cheque)
        return cuota, cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número y banco.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc


def cobrar_cuotas_lote(
    db: Session,
    prestamo_id: uuid.UUID,
    cuota_ids: list[uuid.UUID],
    fecha_cobro: date | None = None,
    cotizacion_stock: Decimal | None = None,
    medio_pago: MedioPago = MedioPago.EFECTIVO,
) -> list[Cuota]:
    cuotas = list(
        db.scalars(
            select(Cuota)
            .where(Cuota.prestamo_id == prestamo_id, Cuota.id.in_(cuota_ids))
            .with_for_update()
        )
    )
    if len(cuotas) != len(cuota_ids):
        raise NotFoundError("Una o más cuotas no fueron encontradas.")
    for cuota in cuotas:
        if cuota.estado == CuotaEstado.COBRADA:
            raise ConflictError(f"La cuota {cuota.numero_cuota} ya fue cobrada.")

    hoy = fecha_cobro or hoy_local()
    restantes: dict[uuid.UUID, Decimal] = {}
    for cuota in cuotas:
        restantes[cuota.id] = (cuota.monto - cuota.monto_pagado).quantize(Decimal("0.01"))
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = hoy

    try:
        db.flush()
        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            for cuota in cuotas:
                _registrar_cobro_cuota(
                    db, prestamo, cuota, restantes[cuota.id],
                    medio_pago, cotizacion_stock,
                )
        if prestamo is not None:
            recalcular_estado(prestamo)
        db.commit()
        for cuota in cuotas:
            db.refresh(cuota)
        return cuotas
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro de las cuotas.") from exc


def cobrar_cuotas_con_cheque_lote(
    db: Session,
    prestamo_id: uuid.UUID,
    payload: CuotasLoteCobrarConChequeRequest,
) -> tuple[list[Cuota], Cheque]:
    cuotas = list(
        db.scalars(
            select(Cuota)
            .where(Cuota.prestamo_id == prestamo_id, Cuota.id.in_(payload.cuota_ids))
            .with_for_update()
        )
    )
    if len(cuotas) != len(payload.cuota_ids):
        raise NotFoundError("Una o más cuotas no fueron encontradas.")
    for cuota in cuotas:
        if cuota.estado == CuotaEstado.COBRADA:
            raise ConflictError(f"La cuota {cuota.numero_cuota} ya fue cobrada.")

    cheque = Cheque(
        nro_cheque=payload.nro_cheque,
        banco=payload.banco,
        monto=payload.monto,
        porcentaje_compra=payload.porcentaje_compra,
        fecha_emision=payload.fecha_emision,
        fecha_pago=payload.fecha_pago,
        cliente_origen_id=payload.cliente_origen_id,
        estado=ChequeEstado.EN_CARTERA,
    )

    hoy = payload.fecha_cobro or hoy_local()
    for cuota in cuotas:
        cuota.monto_pagado = cuota.monto
        cuota.estado = CuotaEstado.COBRADA
        cuota.fecha_cobro = hoy

    try:
        db.add(cheque)
        db.flush()
        prestamo = db.get(Prestamo, prestamo_id)
        if prestamo is not None:
            recalcular_estado(prestamo)
        db.commit()
        for cuota in cuotas:
            db.refresh(cuota)
        db.refresh(cheque)
        return cuotas, cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError("Ya existe un cheque con ese número y banco.") from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el cobro con cheque.") from exc


def repartir_pago_en_cuotas(
    saldos: list[Decimal], monto: Decimal
) -> list[Decimal]:
    """Reparte `monto` entre cuotas (por su saldo, en orden) llenando cada una.

    `saldos` es el saldo pendiente de cada cuota, ordenado como se quiera imputar
    (la más vieja primero). Devuelve cuánto se aplica a cada cuota, en el mismo
    orden. La suma de lo devuelto es `min(monto, Σ saldos)`: no reparte de más.
    Pura (sin BD): testeable en el estilo de `tests/`."""
    restante = monto
    aplicado: list[Decimal] = []
    for saldo in saldos:
        cuota_saldo = saldo if saldo > Decimal("0.00") else Decimal("0.00")
        aplica = min(restante, cuota_saldo) if restante > Decimal("0.00") else Decimal("0.00")
        aplica = aplica.quantize(Decimal("0.01"))
        aplicado.append(aplica)
        restante = (restante - aplica).quantize(Decimal("0.01"))
    return aplicado


def imputar_pago(
    db: Session,
    prestamo: Prestamo,
    *,
    reduccion: Decimal,
    fecha: date,
    monto_caja: Decimal | None,
    moneda_pago: Moneda,
    medio_pago: MedioPago,
    cotizacion: Decimal | None,
    cotizacion_stock: Decimal | None = None,
) -> bool:
    """Imputa `reduccion` (en la moneda del préstamo) a las cuotas más viejas.

    **No commitea**: deja todo en la sesión para que el commit sea del servicio
    que orquesta la operación. Es lo que permite que el cobro consolidado por
    cliente (`svc_deudores`) toque un préstamo, un fiado y una deuda libre en
    una sola transacción sin duplicar acá las reglas de este módulo.

    `monto_caja` es la plata que entró **por este préstamo**, en `moneda_pago`;
    `None` significa que la operación no mueve caja —el cobro con cheque, donde
    la plata se reconoce recién al venderlo o cobrarlo—. Es **una sola línea**
    por el efectivo real, no una por cuota: la referencia es el préstamo.

    Devuelve si el préstamo quedó cancelado."""
    pendientes = [c for c in prestamo.cuotas_detalle if c.estado != CuotaEstado.COBRADA]
    pendientes.sort(key=lambda c: c.numero_cuota)

    aplicado = repartir_pago_en_cuotas(
        [(c.monto - c.monto_pagado).quantize(Decimal("0.01")) for c in pendientes],
        reduccion,
    )
    for cuota, aplica in zip(pendientes, aplicado):
        if aplica <= Decimal("0.00"):
            continue
        cuota.monto_pagado = (cuota.monto_pagado + aplica).quantize(Decimal("0.01"))
        if cuota.monto_pagado >= cuota.monto:
            cuota.monto_pagado = cuota.monto
            cuota.estado = CuotaEstado.COBRADA
            cuota.fecha_cobro = fecha

    # En el interés fijo saldar todas las cuotas NO cancela el préstamo: esas
    # cuotas son interés y el capital sigue afuera (§Interés fijo).
    recalcular_estado(prestamo)
    cancelado = prestamo.estado == PrestamoEstado.CANCELADO

    if monto_caja is None or monto_caja <= Decimal("0.00"):
        return cancelado

    # Una sola línea de caja por el efectivo real que entró, en la moneda pagada.
    cliente_nombre = prestamo.cliente.nombre if prestamo.cliente else "—"
    detalle = f"Pago préstamo - {cliente_nombre}"
    if cotizacion is not None:
        detalle += f" ({reduccion} {prestamo.moneda.value} @ {cotizacion})"
    svc_caja.registrar(
        db,
        fecha=fecha,
        moneda=moneda_pago,
        tipo=CajaTipo.INGRESO,
        categoria=CajaCategoria.COBRO_CUOTA,
        monto=monto_caja,
        medio_pago=medio_pago,
        referencia_tipo="prestamo",
        referencia_id=prestamo.id,
        detalle=detalle,
        cotizacion=cotizacion,
    )
    _ingresar_stock_cobro(
        db,
        prestamo,
        monto=monto_caja,
        moneda_pago=moneda_pago,
        # Si el pago cruzó monedas el operador ya declaró una cotización: esa es
        # el costo, no hace falta pedirle otra por lo mismo.
        cotizacion_stock=cotizacion_stock or cotizacion,
        fecha=fecha,
        detalle=f"Stock por {detalle}",
    )
    return cancelado


def pagar_prestamo(
    db: Session, prestamo_id: uuid.UUID, payload: PrestamoPagoRequest
) -> Prestamo:
    """Paga un importe libre (parcial o total) contra un préstamo, en efectivo.

    El importe se imputa a las cuotas no saldadas, de la más vieja a la más nueva,
    llenando el `monto_pagado` de cada una (la que se completa pasa a COBRADA). El
    pago puede venir en otra moneda que la del préstamo: la cotización define cuánto
    del préstamo (en su moneda) queda saldado, pero la caja recibe la plata en la
    moneda efectivamente pagada. Cuando no queda ninguna cuota pendiente, el préstamo
    pasa a CANCELADO."""
    prestamo = db.scalar(
        select(Prestamo)
        .options(selectinload(Prestamo.cuotas_detalle))
        .where(Prestamo.id == prestamo_id)
        .with_for_update()
    )
    if prestamo is None:
        raise NotFoundError("Prestamo no encontrado.")
    if prestamo.estado == PrestamoEstado.CANCELADO:
        raise ConflictError("El préstamo ya está cancelado.")
    # En el interés fijo el pago libre salda **interés**, nunca capital: se
    # imputa a los períodos impagos del más viejo al más nuevo (primero la mora).
    devengar_periodos(db, prestamo)

    pendientes = [
        c for c in prestamo.cuotas_detalle if c.estado != CuotaEstado.COBRADA
    ]
    pendientes.sort(key=lambda c: c.numero_cuota)
    saldo_total = sum(
        ((c.monto - c.monto_pagado) for c in pendientes), Decimal("0.00")
    ).quantize(Decimal("0.01"))
    if saldo_total <= Decimal("0.00"):
        if es_interes_fijo(prestamo):
            # Lo que queda es capital, y el capital no se paga por acá: no vive
            # en ninguna cuota contra la que imputar (§Interés fijo).
            raise ConflictError(
                "No hay interés pendiente. Lo que queda es capital: usá "
                "'Abonar capital' o 'Cancelar'."
            )
        raise ConflictError("El préstamo no tiene saldo pendiente.")

    es_cross = payload.moneda_pago != prestamo.moneda
    # Cuánto del préstamo (en su moneda) salda este pago; valida cotización y tope.
    reduccion = calcular_reduccion_saldo(
        prestamo.moneda,
        saldo_total,
        payload.moneda_pago,
        payload.monto_pagado,
        payload.cotizacion,
    )

    fecha = payload.fecha_cobro or hoy_local()
    imputar_pago(
        db,
        prestamo,
        reduccion=reduccion,
        fecha=fecha,
        monto_caja=payload.monto_pagado,
        moneda_pago=payload.moneda_pago,
        cotizacion=payload.cotizacion if es_cross else None,
        medio_pago=payload.medio_pago,
        cotizacion_stock=payload.cotizacion_stock,
    )

    try:
        db.commit()
        return get_prestamo(db, prestamo.id)
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el pago del préstamo.") from exc

