"""anulacion.py — Motor único de anulación y reversión de operaciones.

Régimen definido 2026-08-06. Base común de tres pedidos que son la misma cosa
de fondo —deshacer algo ya asentado en caja—: el botón "Eliminar" del panel, la
reversión desde el panel y la reversión desde el bot.

**Eliminar no borra: anula.** La fila queda con `anulado_at`/`anulado_por`/
`motivo_anulacion`, desaparece de los listados y sus líneas del libro de caja se
revierten. Se conserva la historia para poder auditar después por qué la caja dio
distinto; un `DELETE` físico haría imposible esa reconstrucción.

**Reversión ≠ anulación.** Anular saca la operación entera de circulación; revertir
deshace *una transición* y deja la entidad viva (un cheque VENDIDO vuelve a
EN_CARTERA y se puede volver a vender). Ambas comparten el reverso de caja y la
exigencia de operador + motivo, por eso viven juntas.

Ninguna función hace commit salvo las de la API pública (`anular`, `revertir_cheque`),
que sí lo hacen para que la marca y el reverso de caja sean atómicos.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from decimal import Decimal

from sqlalchemy import select, tuple_
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    AjusteCaja,
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    Compensacion,
    DeudaSimple,
    Fiado,
    GastoOperativo,
    Moneda,
    MovimientoCaja,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
    Pasivo,
    Prestamo,
)
from app.services import caja as svc_caja
from app.services import stock_usd as svc_stock
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CIEN = Decimal("100")


# ══════════════════════════════════════════════════════════════════════
#  Catálogo de entidades anulables
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class _Spec:
    """Cómo anular un tipo de entidad.

    `refs` son los `referencia_tipo` del libro de caja que le pertenecen. Una
    entidad puede tener varios: una deuda simple asienta el egreso de origen con
    `deuda_simple` y cada cobro con `deuda_simple_cobro`, y anularla tiene que
    barrer los dos.
    """

    modelo: type
    refs: tuple[str, ...]
    label: str


_ENTIDADES: dict[str, _Spec] = {
    "cheque":             _Spec(Cheque,             ("cheque",),                            "cheque"),
    "prestamo":           _Spec(Prestamo,           ("prestamo", "cuota"),                  "préstamo"),
    "movimiento_efectivo": _Spec(MovimientoEfectivo, ("movimiento_efectivo",),              "operación de divisas"),
    "fiado":              _Spec(Fiado,              ("fiado",),                             "cheque fiado"),
    "deuda_simple":       _Spec(DeudaSimple,        ("deuda_simple", "deuda_simple_cobro"), "deuda"),
    "pasivo":             _Spec(Pasivo,             ("pasivo",),                            "deuda del negocio"),
    "gasto":              _Spec(GastoOperativo,     ("gasto",),                             "gasto"),
    "ajuste_caja":        _Spec(AjusteCaja,         ("ajuste_caja",),                       "ajuste de caja"),
    # Sin refs: una compensación no asienta nada en el libro de caja —esa plata
    # nunca pasó por acá—, así que no hay líneas que revertir. Lo que hay que
    # deshacer son los saldos de los dos lados, y de eso se encarga
    # `svc_compensaciones.revertir` (ver `anular`).
    "compensacion":       _Spec(Compensacion,       (),                                     "compensación"),
}


def _spec(entidad: str) -> _Spec:
    spec = _ENTIDADES.get(entidad)
    if spec is None:
        validos = ", ".join(sorted(_ENTIDADES))
        raise ValidationError(f"Tipo de entidad '{entidad}' desconocido. Válidos: {validos}.")
    return spec


# Movimientos de **stock de dólares** que cuelgan de cada entidad (§Stock de
# dólares, migración `0025`): la salida de stock de lo que se otorgó o gastó en
# USD, y la entrada de lo que se cobró en USD. Anular la operación los borra —si
# no existió, esos dólares no entraron ni salieron—, y eso obliga a reimputar el
# FIFO. **Una entidad que mueva stock se da de alta acá**, o al anularla sus
# dólares quedarían dando vueltas en la cadena: prestando su costo a una ganancia
# futura, o consumiendo un stock que ya nadie sacó.
_ORIGENES_STOCK: dict[str, tuple[str, ...]] = {
    "gasto":        ("gasto",),
    "deuda_simple": ("deuda_simple", "deuda_simple_cobro"),
    "prestamo":     ("prestamo", "prestamo_cobro"),
    "fiado":        ("fiado_cobro",),
    "pasivo":       ("pasivo_pago",),
}


def _bloqueo_stock(db: Session, entidad: str, entidad_id: uuid.UUID) -> str | None:
    """Impide anular si los dólares que entraron con esta operación ya se vendieron.

    Quitar ese lote dejaría esas ventas sin el stock del que salieron y
    reescribiría su ganancia ya reportada. Mismo criterio que anular un ajuste en
    USD o un préstamo recibido en dólares (§5)."""
    for origen in _ORIGENES_STOCK.get(entidad, ()):
        for mov in svc_stock.listar_por_origen(db, origen, entidad_id):
            if mov.tipo == MovimientoEfectivoTipo.COMPRA and mov.usd_restante != mov.monto:
                consumido = mov.monto - mov.usd_restante
                return (
                    f"No se puede anular: {consumido} de los {mov.monto} USD que "
                    "entraron con esta operación ya se vendieron. Anulá primero esas ventas."
                )
    return None


# ══════════════════════════════════════════════════════════════════════
#  Previsualización del impacto
# ══════════════════════════════════════════════════════════════════════

@dataclass
class LineaImpacto:
    fecha: str
    moneda: str
    tipo: str
    categoria: str
    monto: Decimal
    detalle: str | None


@dataclass
class Impacto:
    """Qué pasaría si se anulara: se muestra al operador ANTES de confirmar."""

    entidad: str
    entidad_id: uuid.UUID
    descripcion: str
    bloqueo: str | None = None
    lineas: list[LineaImpacto] = field(default_factory=list)
    arrastra: list[str] = field(default_factory=list)

    @property
    def puede_anular(self) -> bool:
        return self.bloqueo is None


def _lineas_de_caja(db: Session, refs: tuple[str, ...], entidad_id: uuid.UUID) -> list[LineaImpacto]:
    movs = db.scalars(
        select(MovimientoCaja)
        .where(
            MovimientoCaja.referencia_tipo.in_(refs),
            MovimientoCaja.referencia_id == entidad_id,
        )
        .order_by(MovimientoCaja.fecha.asc())
    )
    return [
        LineaImpacto(
            fecha=m.fecha.isoformat(),
            moneda=m.moneda.value,
            tipo=m.tipo.value,
            categoria=m.categoria.value,
            monto=m.monto,
            detalle=m.detalle,
        )
        for m in movs
    ]


def previsualizar(db: Session, entidad: str, entidad_id: uuid.UUID) -> Impacto:
    """Devuelve el impacto de anular, sin tocar nada.

    El panel lo usa para mostrar "esto es lo que se va a revertir" antes de que el
    operador confirme. Si hay un bloqueo, viene explicado en `bloqueo` y el botón
    de confirmar queda deshabilitado.
    """
    spec = _spec(entidad)
    obj = db.get(spec.modelo, entidad_id)
    if obj is None:
        raise NotFoundError(f"No se encontró {spec.label} con ese identificador.")

    impacto = Impacto(
        entidad=entidad,
        entidad_id=entidad_id,
        descripcion=_describir(obj, spec),
        lineas=_lineas_de_caja(db, spec.refs, entidad_id),
    )

    if getattr(obj, "anulado_at", None) is not None:
        impacto.bloqueo = f"Este {spec.label} ya fue anulado el {obj.anulado_at:%d/%m/%Y}."
        return impacto

    bloqueo, arrastra = _validar(db, entidad, obj)
    impacto.bloqueo = bloqueo or _bloqueo_stock(db, entidad, entidad_id)
    impacto.arrastra = arrastra

    # Las cuotas de un préstamo referencian cada una su propio id, no el del
    # préstamo: hay que sumarlas aparte para que el impacto no salga incompleto.
    if entidad == "prestamo":
        impacto.lineas.extend(_lineas_cuotas(db, obj))

    return impacto


def _describir(obj, spec: _Spec) -> str:
    """Texto corto para que el operador reconozca qué está por anular."""
    if isinstance(obj, Cheque):
        banco = f" — {obj.banco}" if obj.banco else ""
        return f"Cheque Nº {obj.nro_cheque}{banco} — ${obj.monto:,.2f} — {obj.estado.value}"
    if isinstance(obj, Prestamo):
        cliente = obj.cliente.nombre if obj.cliente else "sin cliente"
        return f"Préstamo a {cliente} — {obj.moneda.value} {obj.credito:,.2f} — {obj.estado.value}"
    if isinstance(obj, MovimientoEfectivo):
        return f"{obj.tipo.value} de {obj.monto} USD @ ${obj.cotizacion_aplicada}"
    if isinstance(obj, AjusteCaja):
        signo = "+" if obj.tipo == CajaTipo.INGRESO else "−"
        return (
            f"Ajuste de caja {signo}{obj.moneda.value} {obj.monto:,.2f} "
            f"— {obj.motivo.value}"
        )
    if isinstance(obj, Fiado):
        cliente = obj.cliente.nombre if obj.cliente else "sin cliente"
        return f"Fiado de {cliente} — saldo ${obj.saldo_pendiente:,.2f} — {obj.estado.value}"
    if isinstance(obj, DeudaSimple):
        cliente = obj.cliente.nombre if obj.cliente else "sin cliente"
        return f"{obj.concepto} — {cliente} — {obj.moneda.value} {obj.monto:,.2f}"
    if isinstance(obj, Pasivo):
        return f"{obj.concepto} — {obj.acreedor} — {obj.moneda.value} {obj.monto:,.2f}"
    if isinstance(obj, GastoOperativo):
        return f"{obj.concepto} — {obj.moneda.value} {obj.monto:,.2f}"
    if isinstance(obj, Compensacion):
        cliente = obj.cliente.nombre if obj.cliente else "cliente"
        acreedor = obj.pasivo.acreedor if obj.pasivo else "acreedor"
        return (
            f"{cliente} le transfirió {obj.moneda.value} {obj.monto:,.2f} a {acreedor}"
        )
    return spec.label


def _lineas_cuotas(db: Session, prestamo: Prestamo) -> list[LineaImpacto]:
    ids = [c.id for c in prestamo.cuotas_detalle]
    if not ids:
        return []
    movs = db.scalars(
        select(MovimientoCaja)
        .where(
            MovimientoCaja.referencia_tipo == "cuota",
            MovimientoCaja.referencia_id.in_(ids),
        )
        .order_by(MovimientoCaja.fecha.asc())
    )
    return [
        LineaImpacto(
            fecha=m.fecha.isoformat(),
            moneda=m.moneda.value,
            tipo=m.tipo.value,
            categoria=m.categoria.value,
            monto=m.monto,
            detalle=m.detalle,
        )
        for m in movs
    ]


# ══════════════════════════════════════════════════════════════════════
#  Reglas de bloqueo por entidad
# ══════════════════════════════════════════════════════════════════════

def _validar_pasivo_de_origen(
    db: Session, entidad: str, entidad_id: uuid.UUID
) -> tuple[str | None, list[str]]:
    """Qué pasa con el pasivo que generó una compra a deber (§Comprar sin abonar).

    Si la compra se anula, esa deuda deja de existir y el pasivo se va con ella.
    Pero si ya se pagó —entero o en parte— la plata salió de verdad: anular la
    compra dejaría un egreso en el libro sin nada que lo explique, así que se
    bloquea y el operador deshace primero el pago.
    """
    from app.services.pasivos import pasivo_de_origen

    pasivo = pasivo_de_origen(db, entidad, entidad_id)
    if pasivo is None:
        return None, []
    if pasivo.saldo_pendiente != pasivo.monto:
        return (
            f"Esta compra quedó a deber y ya se le pagó a {pasivo.acreedor}. "
            "Revertí primero ese pago desde la sección Deudas.",
            [],
        )
    return None, [f"la deuda con {pasivo.acreedor} (${pasivo.saldo_pendiente:,.2f})"]


def _validar(db: Session, entidad: str, obj) -> tuple[str | None, list[str]]:
    """Devuelve (motivo_de_bloqueo | None, cosas_que_arrastra).

    Bloquea cuando anular dejaría el sistema en un estado que no se puede
    reconstruir solo (por ejemplo, romper la cadena FIFO de divisas). Cuando la
    anulación arrastra entidades dependientes, las lista para avisar al operador.
    """
    if entidad == "cheque":
        return _validar_cheque(db, obj)
    if entidad == "movimiento_efectivo":
        return _validar_movimiento(db, obj)
    if entidad == "fiado":
        return _validar_fiado(obj)
    if entidad == "ajuste_caja":
        return _validar_ajuste(db, obj)
    if entidad == "pasivo":
        return _validar_pasivo(db, obj)
    return None, []


def _validar_pasivo(db: Session, pasivo: Pasivo) -> tuple[str | None, list[str]]:
    """Una deuda se anula siempre, salvo que le haya dado stock al FIFO.

    Es el caso del préstamo recibido en dólares (§5): esos USD entraron al stock
    con su costo, y si ya se vendieron —aunque sea en parte— sacarlos dejaría esas
    ventas sin el lote del que salieron y reescribiría su ganancia ya reportada.
    Mismo criterio que un ajuste en dólares.
    """
    if pasivo.lote_id is None:
        return None, []
    lote = db.get(MovimientoEfectivo, pasivo.lote_id)
    if lote is not None and lote.usd_restante != lote.monto:
        consumido = lote.monto - lote.usd_restante
        return (
            f"No se puede eliminar esta deuda: {consumido} de los {lote.monto} USD que "
            "te prestaron ya fueron vendidos. Anulá primero esas ventas.",
            [],
        )
    return None, [f"el stock de {lote.monto} USD que entró con ese préstamo"] if lote else []


def _validar_ajuste(db: Session, ajuste: AjusteCaja) -> tuple[str | None, list[str]]:
    """Un ajuste en ARS se anula siempre; uno en USD, solo si no trabó el FIFO.

    Anular un ajuste de dólares le devuelve (o le saca) stock a la cadena, y eso
    reescribiría la ganancia de las ventas que vinieron después. Mismo criterio que
    con las operaciones de divisas: hacia atrás solo se deshace la última.
    """
    if ajuste.moneda != Moneda.USD:
        return None, []

    # Sumó dólares: si su lote ya se vendió (aunque sea en parte), sacarlo dejaría
    # esas ventas sin el stock del que salieron.
    if ajuste.lote_id is not None:
        lote = db.get(MovimientoEfectivo, ajuste.lote_id)
        if lote is not None and lote.usd_restante != lote.monto:
            consumido = lote.monto - lote.usd_restante
            return (
                f"No se puede anular este ajuste: {consumido} de los {lote.monto} USD "
                "que agregó ya fueron vendidos. Anulá primero esas ventas.",
                [],
            )
        return None, []

    # Restó dólares: consumió lotes. Devolverlos cambiaría contra qué lote se
    # imputó cada venta posterior, y con eso su ganancia ya reportada.
    posterior = db.scalar(
        select(MovimientoEfectivo.id)
        .where(
            MovimientoEfectivo.tipo == MovimientoEfectivoTipo.VENTA,
            MovimientoEfectivo.anulado_at.is_(None),
            MovimientoEfectivo.fecha_operacion
            >= datetime.combine(ajuste.fecha, time.min, tzinfo=UTC),
        )
        .limit(1)
    )
    if posterior is not None:
        return (
            "Este ajuste sacó dólares del stock y después hubo ventas que dependen "
            "de esa imputación FIFO. Anulá primero esas ventas.",
            [],
        )
    return None, []


def _deuda_inicial_fiado(fiado: Fiado) -> Decimal:
    return (fiado.monto_original * (_CIEN - fiado.porcentaje_venta) / _CIEN).quantize(Decimal("0.01"))


def _validar_fiado(fiado: Fiado) -> tuple[str | None, list[str]]:
    # Un fiado que ya recibió plata del cliente no se puede anular sin decidir qué
    # pasa con esos cobros: se revierte primero el cobro y después el fiado.
    if fiado.saldo_pendiente != _deuda_inicial_fiado(fiado):
        cobrado = _deuda_inicial_fiado(fiado) - fiado.saldo_pendiente
        return (
            f"Este fiado ya recibió cobros por ${cobrado:,.2f}. "
            "Revertí primero esos cobros y después anulá el fiado.",
            [],
        )
    return None, []


def _validar_cheque(db: Session, cheque: Cheque) -> tuple[str | None, list[str]]:
    arrastra: list[str] = []

    fiado = cheque.fiado_originado
    if fiado is not None and fiado.anulado_at is None:
        bloqueo, _ = _validar_fiado(fiado)
        if bloqueo is not None:
            return (
                f"El cheque está FIADO y su deuda ya recibió cobros parciales. {bloqueo}",
                [],
            )
        arrastra.append(f"el fiado asociado (saldo ${fiado.saldo_pendiente:,.2f})")

    # Un cheque entregado para pagar una deuda del negocio dejó su rastro en el
    # pago del pasivo: anularlo por su cuenta descuadraría ese pasivo.
    pago = db.scalar(
        select(MovimientoCaja).where(
            MovimientoCaja.referencia_tipo == "cheque",
            MovimientoCaja.referencia_id == cheque.id,
            MovimientoCaja.categoria.in_(
                (CajaCategoria.PAGO_PASIVO, CajaCategoria.VUELTO_PASIVO)
            ),
        )
    )
    if pago is not None:
        return (
            "Este cheque se usó para pagar una deuda del negocio. "
            "Revertí primero ese pago desde la sección Deudas.",
            [],
        )

    bloqueo, arrastra_pasivo = _validar_pasivo_de_origen(db, "cheque", cheque.id)
    if bloqueo is not None:
        return bloqueo, []
    arrastra.extend(arrastra_pasivo)

    return None, arrastra


def _validar_movimiento(db: Session, mov: MovimientoEfectivo) -> tuple[str | None, list[str]]:
    """Misma regla que editar: no se puede tocar una operación trabada en el FIFO.

    Anular una compra cuyo lote ya fue consumido, o una venta que no es la última,
    reescribiría la ganancia de operaciones posteriores ya reportadas.
    """
    if mov.tipo == MovimientoEfectivoTipo.COMPRA:
        if mov.usd_restante != mov.monto:
            consumido = mov.monto - mov.usd_restante
            return (
                f"No se puede anular esta compra: {consumido} de sus {mov.monto} USD "
                "ya fueron vendidos. Anulá primero esas ventas.",
                [],
            )
        return _validar_pasivo_de_origen(db, "movimiento_efectivo", mov.id)

    # El orden FIFO es (fecha_operacion, created_at): se compara como tupla, igual
    # que en `editar_movimiento`. Comparar los campos por separado dejaría pasar una
    # venta con fecha posterior pero cargada antes.
    posterior = db.scalar(
        select(MovimientoEfectivo.id)
        .where(
            MovimientoEfectivo.tipo == MovimientoEfectivoTipo.VENTA,
            MovimientoEfectivo.anulado_at.is_(None),
            MovimientoEfectivo.id != mov.id,
            tuple_(MovimientoEfectivo.fecha_operacion, MovimientoEfectivo.created_at)
            > (mov.fecha_operacion, mov.created_at),
        )
        .limit(1)
    )
    if posterior is not None:
        return (
            "Solo se puede anular la última venta de dólares: hay ventas posteriores "
            "que dependen de esta imputación FIFO.",
            [],
        )
    return None, []


# ══════════════════════════════════════════════════════════════════════
#  Anulación
# ══════════════════════════════════════════════════════════════════════

def _marcar(obj, operador_id: str, motivo: str) -> None:
    obj.anulado_at = datetime.now(tz=UTC)
    obj.anulado_por = operador_id.strip()
    obj.motivo_anulacion = motivo.strip()


def anular(
    db: Session,
    entidad: str,
    entidad_id: uuid.UUID,
    *,
    operador_id: str,
    motivo: str,
) -> Impacto:
    """Anula una operación y revierte su rastro en el libro de caja.

    Devuelve el `Impacto` con las líneas que se revirtieron, para poder mostrarle
    al operador exactamente qué se deshizo.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador que anula.")
    if not (motivo and motivo.strip()):
        raise ValidationError("Se requiere un motivo para anular la operación.")

    spec = _spec(entidad)

    # La compensación no deja rastro en el libro de caja: deshacerla es devolver
    # saldos en los dos lados (cliente y acreedor), y eso lo sabe hacer su propio
    # servicio. Pasa por acá igual para que el panel y el bot la deshagan por la
    # misma puerta que todo el resto, con operador y motivo.
    if entidad == "compensacion":
        from app.services import compensaciones as svc_compensaciones

        comp = db.get(Compensacion, entidad_id)
        if comp is None:
            raise NotFoundError("No se encontró la compensación con ese identificador.")
        descripcion = _describir(comp, spec)
        restituido = svc_compensaciones.revertir(
            db, entidad_id, operador_id=operador_id, motivo=motivo
        )
        return Impacto(
            entidad=entidad,
            entidad_id=entidad_id,
            descripcion=descripcion,
            lineas=[],
            arrastra=restituido,
        )

    obj = db.scalar(select(spec.modelo).where(spec.modelo.id == entidad_id).with_for_update())
    if obj is None:
        raise NotFoundError(f"No se encontró {spec.label} con ese identificador.")
    if obj.anulado_at is not None:
        raise ConflictError(f"Este {spec.label} ya fue anulado.")

    bloqueo, arrastra = _validar(db, entidad, obj)
    if bloqueo is not None:
        raise ConflictError(bloqueo)

    # Se captura el impacto ANTES de borrar: después las líneas ya no existen.
    lineas = _lineas_de_caja(db, spec.refs, entidad_id)
    if entidad == "prestamo":
        lineas.extend(_lineas_cuotas(db, obj))

    try:
        for ref in spec.refs:
            svc_caja.borrar_por_referencia(db, ref, entidad_id)

        # Las cuotas cobradas asientan con su propio id: hay que barrerlas una a una.
        if entidad == "prestamo":
            for cuota in obj.cuotas_detalle:
                svc_caja.borrar_por_referencia(db, "cuota", cuota.id)

        # Una compra a deber arrastra el pasivo que generó (ya validado sin pagos
        # encima): si la compra no existió, esa plata no se le debe a nadie.
        if entidad in ("cheque", "movimiento_efectivo"):
            from app.services.pasivos import pasivo_de_origen

            pasivo = pasivo_de_origen(db, entidad, entidad_id)
            if pasivo is not None:
                _marcar(pasivo, operador_id, f"Anulado en cascada: {motivo.strip()}")

        # Un cheque fiado arrastra su fiado (ya validado sin cobros encima).
        if entidad == "cheque" and obj.fiado_originado is not None:
            fiado = obj.fiado_originado
            if fiado.anulado_at is None:
                svc_caja.borrar_por_referencia(db, "fiado", fiado.id)
                _marcar(fiado, operador_id, f"Anulado en cascada con el cheque Nº {obj.nro_cheque}")

        # Anular el fiado deshace la entrega a crédito: el cheque no se entregó,
        # así que vuelve a cartera. Si no, quedaría FIADO sin nadie debiendo.
        if entidad == "fiado":
            cheque = obj.cheque
            if cheque is not None and cheque.anulado_at is None and cheque.estado == ChequeEstado.FIADO:
                cheque.estado = ChequeEstado.EN_CARTERA
                cheque.porcentaje_venta = None
                cheque.cliente_destino_id = None
                cheque.ultimo_operador_id = operador_id.strip()
                cheque.ultimo_motivo_manual = f"Vuelto a cartera al eliminar el fiado: {motivo.strip()}"
                cheque.ultimo_evento_manual_at = datetime.now(tz=UTC)

        # Anular un ajuste que sumó dólares se lleva su lote: ese stock no existió.
        # Se borra en serio (no se anula) porque el lote no es una operación con
        # historia propia, es el reflejo del ajuste — que sí queda anulado y auditable.
        if entidad == "ajuste_caja" and obj.lote_id is not None:
            lote = db.get(MovimientoEfectivo, obj.lote_id)
            obj.lote_id = None
            if lote is not None:
                db.delete(lote)

        # Ídem con el préstamo recibido en dólares (§5): si la deuda no existió,
        # esos dólares tampoco entraron al stock (ya validado sin ventas encima).
        if entidad == "pasivo" and obj.lote_id is not None:
            lote = db.get(MovimientoEfectivo, obj.lote_id)
            obj.lote_id = None
            if lote is not None:
                db.delete(lote)

        # Los dólares que esta operación movió salen de la cadena con ella
        # (§Stock de dólares). `borrar_por_origen` vuelve a validar lo que ya
        # chequeó `_bloqueo_stock`: es la última barrera si alguien anula sin
        # pasar por la previsualización.
        origenes_stock = _ORIGENES_STOCK.get(entidad, ())
        for origen in origenes_stock:
            svc_stock.borrar_por_origen(db, origen, entidad_id)

        _marcar(obj, operador_id, motivo)

        if origenes_stock:
            from app.services.movimientos import _reimputar_fifo

            db.flush()
            _reimputar_fifo(db)

        # Sacar ese stock de la cadena obliga a recalcular las imputaciones FIFO.
        if entidad == "pasivo" and obj.moneda == Moneda.USD and obj.ingreso_caja:
            from app.services.movimientos import _reimputar_fifo

            db.flush()
            _reimputar_fifo(db)

        # Un ajuste en dólares aporta o consume stock: sacarlo de la cadena obliga
        # a recalcular, igual que una operación de divisas.
        if entidad == "ajuste_caja" and obj.moneda == Moneda.USD:
            from app.services.movimientos import _reimputar_fifo

            db.flush()
            _reimputar_fifo(db)

        # Sacar una operación de divisas de la cadena obliga a recalcular el FIFO.
        if entidad == "movimiento_efectivo":
            from app.services.movimientos import _reimputar_fifo

            # La sesión va con autoflush=False: sin este flush explícito, el SELECT
            # de _reimputar_fifo no vería el `anulado_at` recién marcado y la
            # operación anulada seguiría aportando (o consumiendo) stock USD.
            db.flush()
            _reimputar_fifo(db)

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError(f"No se pudo anular el {spec.label}.") from exc

    return Impacto(
        entidad=entidad,
        entidad_id=entidad_id,
        descripcion=_describir(obj, spec),
        lineas=lineas,
        arrastra=arrastra,
    )


# ══════════════════════════════════════════════════════════════════════
#  Reversión de transiciones del cheque
# ══════════════════════════════════════════════════════════════════════

# Estados terminales que se pueden deshacer para volver a EN_CARTERA. La máquina
# de estados los declara terminales a propósito; esta es la única puerta que los
# abre, y solo hacia atrás, con operador y motivo registrados.
_REVERTIBLES: frozenset[ChequeEstado] = frozenset({
    ChequeEstado.VENDIDO,
    ChequeEstado.FIADO,
    ChequeEstado.COBRADO,
    ChequeEstado.RECHAZADO,
})


def revertir_cheque(
    db: Session,
    cheque_id: uuid.UUID,
    *,
    operador_id: str,
    motivo: str,
) -> Cheque:
    """Devuelve un cheque terminal (VENDIDO/FIADO/COBRADO/RECHAZADO) a EN_CARTERA.

    A diferencia de anular, el cheque sigue vivo: vuelve a estar disponible para
    venderlo o fiarlo de nuevo. Se borra el ingreso de venta/cobro del libro de
    caja y se conserva el egreso de la compra, que sigue siendo cierto (la plata
    para comprar el cheque salió igual).
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador que revierte.")
    if not (motivo and motivo.strip()):
        raise ValidationError("Se requiere un motivo para revertir la operación.")

    cheque = db.scalar(select(Cheque).where(Cheque.id == cheque_id).with_for_update())
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if cheque.anulado_at is not None:
        raise ConflictError("El cheque está anulado.")
    if cheque.estado == ChequeEstado.EN_CARTERA:
        raise ConflictError("El cheque ya está EN_CARTERA: no hay nada que revertir.")
    if cheque.estado not in _REVERTIBLES:
        raise ConflictError(f"No se puede revertir un cheque en estado {cheque.estado.value}.")

    fiado = cheque.fiado_originado
    if cheque.estado == ChequeEstado.FIADO and fiado is not None and fiado.anulado_at is None:
        bloqueo, _ = _validar_fiado(fiado)
        if bloqueo is not None:
            raise ConflictError(
                f"No se puede revertir el fiado de este cheque. {bloqueo}"
            )

    try:
        # El egreso de compra se conserva; se rehace solo el tramo de venta/cobro.
        from app.services.cheques import resync_caja_cheque

        cheque.estado = ChequeEstado.EN_CARTERA
        cheque.porcentaje_venta = None
        cheque.ganancia = Decimal("0.00")
        cheque.cliente_destino_id = None
        cheque.ultimo_operador_id = operador_id.strip()
        cheque.ultimo_motivo_manual = f"Reversión: {motivo.strip()}"
        cheque.ultimo_evento_manual_at = datetime.now(tz=UTC)

        # El fiado se anula (no se "cancela"): cancelado significa que el cliente
        # pagó, y acá no pagó nadie — la operación no existió.
        if fiado is not None and fiado.anulado_at is None:
            svc_caja.borrar_por_referencia(db, "fiado", fiado.id)
            _marcar(fiado, operador_id, f"Revertido junto con el cheque Nº {cheque.nro_cheque}")

        resync_caja_cheque(db, cheque)
        db.commit()
        db.refresh(cheque)
        return cheque
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo revertir la operación del cheque.") from exc
