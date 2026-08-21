from __future__ import annotations

import difflib
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.db.models import (
    Compensacion,
    CajaCategoria,
    CajaTipo,
    Cheque,
    Cliente,
    Cuota,
    CuotaEstado,
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    GastoOperativo,
    Pasivo,
    PasivoEstado,
    Prestamo,
    PrestamoEstado,
    ChequeEstado,
    FrecuenciaCuotas,
    Moneda,
    MovimientoCaja,
    MovimientoEfectivo,
    MovimientoEfectivoTipo,
)
from app.schemas.gastos_operativos import GastoOperativoCreate
from app.services import gastos_operativos as svc_gastos
from app.schemas.pasivos import PasivoCreate, PasivoUpdate
from app.services import pasivos as svc_pasivos
from app.schemas.cheques import ChequeFiarRequest, ChequeCreate, ChequeManualTransition
from app.schemas.clientes import ClienteCreate
from app.schemas.deudas_simples import DeudaSimpleCreate
from app.services import deudas_simples as svc_deudas_simples
from app.schemas.compensaciones import CompensacionCreate
from app.schemas.deudores import CobroClienteCreate
from app.services import compensaciones as svc_compensaciones
from app.services import deudores as svc_deudores
from app.schemas.fiados import FiadoCobrarConChequeRequest, FiadoCobrarEfectivoRequest
from app.schemas.movimientos import MovimientoEfectivoCreate
from app.schemas.prestamos import PrestamoCreate
from app.services import anulacion as svc_anulacion
from app.services import caja as svc_caja
from app.services import cheques as svc_cheques
from app.services import clientes as svc_clientes
from app.services import fiados as svc_fiados
from app.services import movimientos as svc_movimientos
from app.services import prestamos as svc_prestamos
from app.services import reportes as svc_reportes
from app.core.fechas import fecha_local, hora_local, hoy_local
from app.services.exceptions import ServiceError, ValidationError
from app.services.ia.claude import IntentResult

logger = logging.getLogger(__name__)

# ── Tipos de retorno ─────────────────────────────────────────────────────────
# (limpiar_sesion, texto_respuesta_whatsapp)
DispatchResult = tuple[bool, str]


class ConfirmacionRequerida(Exception):
    """Señal de control: el handler necesita que el operador confirme antes de impactar la BD.

    La levanta un handler (ej: gasto sospechoso de duplicado) y la captura el webhook,
    que guarda el intent como pendiente y le manda el aviso al operador. Si confirma,
    se re-despacha el mismo intent con la marca de confirmado y se ejecuta.
    """

    def __init__(self, mensaje: str) -> None:
        super().__init__(mensaje)
        self.mensaje = mensaje

_FRECUENCIA_PLURAL: dict[FrecuenciaCuotas, str] = {
    FrecuenciaCuotas.DIARIA:    "diarias",
    FrecuenciaCuotas.SEMANAL:   "semanales",
    FrecuenciaCuotas.QUINCENAL: "quincenales",
    FrecuenciaCuotas.MENSUAL:   "mensuales",
    FrecuenciaCuotas.ANUAL:     "anuales",
}


# ────────────────────────────────────────────────────────────────────────────
# Entrypoint público
# ────────────────────────────────────────────────────────────────────────────

def dispatch(
    db: Session,
    phone: str,
    result: IntentResult,
    msg_at: datetime | None = None,
    foto: tuple[bytes, str] | None = None,
) -> DispatchResult:
    """Ejecuta la operación correspondiente al intent y devuelve la respuesta.

    Returns:
        (limpiar_sesion, texto_para_whatsapp)
        limpiar_sesion=True solo cuando se impactó exitosamente la BD.
    """
    intent = result.intent
    data = result.data

    try:
        if intent == "REGISTRAR_CHEQUE":
            return _registrar_cheque(db, phone, data, msg_at, foto)
        if intent == "VENDER_CHEQUE":
            return _vender_cheque(db, phone, data, msg_at)
        if intent == "FIAR_CHEQUE":
            return _fiar_cheque(db, phone, data, msg_at)
        if intent == "COBRAR_CHEQUE":
            return _cobrar_cheque(db, phone, data, msg_at)
        if intent == "RECHAZAR_CHEQUE":
            return _rechazar_cheque(db, phone, data, msg_at)
        if intent == "NUEVO_PRESTAMO":
            return _nuevo_prestamo(db, data, msg_at)
        if intent == "COBRAR_CUOTA":
            return _cobrar_cuota(db, data, msg_at)
        if intent == "COBRAR_FIADO_EFECTIVO":
            return _cobrar_fiado_efectivo(db, phone, data)
        if intent == "COBRAR_FIADO_CON_CHEQUE":
            return _cobrar_fiado_con_cheque(db, phone, data, msg_at)
        if intent == "COBRAR_DEUDA_CLIENTE":
            return _cobrar_deuda_cliente(db, data, msg_at)
        if intent == "COMPENSAR_DEUDA":
            return _compensar_deuda(db, data, msg_at)
        if intent == "REGISTRAR_DEUDA":
            return _registrar_deuda(db, data, msg_at)
        if intent == "REGISTRAR_DEUDA_CLIENTE":
            return _registrar_deuda_cliente(db, data, msg_at)
        if intent == "MOVIMIENTO_EFECTIVO":
            return _movimiento_efectivo(db, data, msg_at)
        if intent == "REGISTRAR_GASTO":
            return _registrar_gasto(db, data, msg_at)
        if intent == "CONSULTA":
            return _consulta(db, data)
        if intent in _CONSULTAS_LEGACY:
            # Contrato anterior (un intent por consulta). Una sesión abierta puede
            # traerlos en el historial: se mapean al tipo equivalente en vez de
            # caer en la respuesta genérica a mitad de conversación.
            return _consulta(db, {**data, "tipo": _CONSULTAS_LEGACY[intent]})
        if intent == "EDITAR_OPERACION":
            return _editar_operacion(db, data)
        if intent == "REVERTIR_OPERACION":
            return _revertir_operacion(db, phone, data)
        # ACLARACION_REQUERIDA y DESCONOCIDO no tocan la BD
        return False, result.respuesta_usuario or "❓ No entendí. ¿Podés repetirlo?"

    except ConfirmacionRequerida:
        raise  # señal de control: la maneja el webhook, no es un error
    except ServiceError as exc:
        return False, f"⚠️ {exc.message}"
    except ValueError as exc:
        return False, f"⚠️ {exc}"
    except Exception as exc:
        logger.exception("Error inesperado en dispatcher (intent=%s): %s", intent, exc)
        return False, "⚠️ Error interno del sistema. El administrador fue notificado."


# ────────────────────────────────────────────────────────────────────────────
# Handlers por intent
# ────────────────────────────────────────────────────────────────────────────

def _items_o_uno(data: dict[str, Any], clave: str) -> list[dict[str, Any]]:
    """Normaliza el payload del modelo a una lista de ítems.

    El bot acepta varios cheques por mensaje (una foto puede traer 4), así que el
    modelo devuelve un array. Se tolera el formato viejo de un solo objeto con los
    campos sueltos: una sesión que quedó abierta con historial del formato anterior
    sigue funcionando en vez de romper a mitad de una conversación.
    """
    items = data.get(clave)
    if isinstance(items, list) and items:
        return [i for i in items if isinstance(i, dict)]
    return [data]


def _registrar_cheque(
    db: Session,
    phone: str,
    data: dict[str, Any],
    msg_at: datetime | None = None,
    foto: tuple[bytes, str] | None = None,
) -> DispatchResult:
    """Alta de uno o varios cheques (una foto puede traer varios).

    Si alguno falla —típicamente porque ya estaba cargado— **se cargan los demás
    igual** y se informa cuál falló y por qué (decisión del dueño, 2026-08-06): así
    no hay que volver a sacar la foto de los cuatro por culpa de uno repetido.
    """
    items = _items_o_uno(data, "cheques")

    if len(items) == 1:
        return _registrar_un_cheque(db, items[0], msg_at, foto)

    cargados: list[str] = []
    fallidos: list[str] = []
    for item in items:
        try:
            _registrar_un_cheque(db, item, msg_at, foto)
            nro = str(item.get("nro_cheque", "?"))
            banco = f" — {item['banco']}" if item.get("banco") else ""
            monto = item.get("monto")
            monto_txt = f" · {_ars(Decimal(str(monto)))}" if monto is not None else ""
            cargados.append(f"  • Nº {nro}{banco}{monto_txt}")
        except (ServiceError, ValueError) as exc:
            motivo = getattr(exc, "message", None) or str(exc)
            fallidos.append(f"  • Nº {item.get('nro_cheque', '?')}: {motivo}")

    lines: list[str] = []
    if cargados:
        lines.append(f"✅ *{len(cargados)} cheque(s) en cartera*")
        lines.extend(cargados)
    if fallidos:
        if cargados:
            lines.append("")
        lines.append(f"⚠️ *{len(fallidos)} no se pudo(eron) cargar*")
        lines.extend(fallidos)
        lines.append("")
        lines.append("Corregí esos y mandámelos de nuevo; los de arriba ya quedaron.")
    return bool(cargados), "\n".join(lines)


def _registrar_un_cheque(
    db: Session,
    data: dict[str, Any],
    msg_at: datetime | None = None,
    foto: tuple[bytes, str] | None = None,
) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
    banco = (str(data["banco"]).strip() or None) if data.get("banco") else None
    monto = _req_decimal(data, "monto")
    pct_compra = _req_decimal(data, "porcentaje_compra")
    fecha_emision = _opt_date(data, "fecha_emision")
    fecha_pago = _opt_date(data, "fecha_pago")

    cliente_id: uuid.UUID | None = None
    if cliente_nombre := data.get("cliente_nombre"):
        cliente = _find_or_create_cliente(db, str(cliente_nombre))
        cliente_id = cliente.id

    # Comprado a deber: `monto_abonado` es lo que se pagó en el acto (0 si nada).
    # El schema lo valida contra el valor neto y exige el vendedor.
    monto_abonado = _opt_decimal(data, "monto_abonado")

    payload = ChequeCreate(
        nro_cheque=nro,
        banco=banco,
        monto=monto,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        porcentaje_compra=pct_compra,
        cliente_origen_id=cliente_id,
        monto_abonado=monto_abonado,
    )
    foto_bytes, foto_mime = foto if foto else (None, None)
    cheque = svc_cheques.create_cheque(
        db, payload, created_at=msg_at, foto=foto_bytes, foto_mime=foto_mime
    )

    lines = [
        f"✅ *Cheque registrado en cartera*",
        f"Nº {cheque.nro_cheque}" + (f" — {cheque.banco}" if cheque.banco else ""),
        f"Monto: {_ars(cheque.monto)}",
        f"Compra: {_pct(cheque.porcentaje_compra)}%",
    ]
    if cheque.fecha_pago:
        lines.append(f"Pago: {_fmt_date(cheque.fecha_pago)}")

    # Cuánto salió de la caja: el control inmediato del operador sobre si el bot
    # entendió que el cheque se pagó o quedó a deber.
    neto = (cheque.monto * (Decimal("100") - cheque.porcentaje_compra) / Decimal("100")).quantize(Decimal("0.01"))
    abonado, a_deber = svc_pasivos.repartir_compra(neto, cheque.monto_abonado)
    lines.append(f"Salió de caja: {_ars(abonado)}")
    if a_deber > 0:
        lines.append(f"⚠️ Queda a deber: {_ars(a_deber)}")

    # Se registra igual (human in the loop); solo avisamos para que el operador revise.
    advertencias = _advertencias_cheque(fecha_emision, fecha_pago)
    if advertencias:
        lines.append("")
        lines.extend(advertencias)
    return True, "\n".join(lines)


def _vender_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    """Venta de uno o varios cheques en un solo mensaje.

    Misma política que el alta: los que se pueden vender se venden, y se informa
    cuál falló (por ejemplo si ya estaba vendido) sin tirar abajo el resto."""
    items = _items_o_uno(data, "ventas")

    if len(items) == 1:
        return _vender_un_cheque(db, phone, items[0], msg_at)

    vendidos: list[str] = []
    fallidos: list[str] = []
    ganancia_total = Decimal("0.00")
    for item in items:
        try:
            cheque = _vender_un_cheque_obj(db, phone, item, msg_at)
            ganancia_total += cheque.ganancia or Decimal("0.00")
            aviso = " ⚠️ a pérdida" if (cheque.ganancia or 0) < 0 else ""
            vendidos.append(
                f"  • Nº {cheque.nro_cheque} al {_pct(cheque.porcentaje_venta)}% "
                f"· {_ars(cheque.ganancia)}{aviso}"
            )
        except (ServiceError, ValueError) as exc:
            motivo = getattr(exc, "message", None) or str(exc)
            fallidos.append(f"  • Nº {item.get('nro_cheque', '?')}: {motivo}")

    lines: list[str] = []
    if vendidos:
        lines.append(f"✅ *{len(vendidos)} cheque(s) vendido(s)*")
        lines.extend(vendidos)
        lines.append("")
        lines.append(f"Ganancia total: {_ars(ganancia_total)}")
    if fallidos:
        if vendidos:
            lines.append("")
        lines.append(f"⚠️ *{len(fallidos)} no se pudo(eron) vender*")
        lines.extend(fallidos)
    return bool(vendidos), "\n".join(lines)


def _vender_un_cheque_obj(
    db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None
) -> Cheque:
    """Vende un cheque y devuelve la fila, para poder resumir el lote."""
    objetivo = _resolver_cheque(db, data)
    pct_venta = _req_decimal(data, "porcentaje_venta")

    cliente_destino_id: uuid.UUID | None = None
    if cliente_nombre := data.get("cliente_nombre"):
        cliente = _find_or_create_cliente(db, str(cliente_nombre))
        cliente_destino_id = cliente.id

    payload = ChequeManualTransition(
        target_state=ChequeEstado.VENDIDO,
        operador_id=phone,
        motivo="Venta registrada por operador",
        porcentaje_venta=pct_venta,
        cliente_destino_id=cliente_destino_id,
    )
    return svc_cheques.transition_cheque(db, objetivo.id, payload, event_at=msg_at)


def _vender_un_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    objetivo = _resolver_cheque(db, data)
    pct_venta = _req_decimal(data, "porcentaje_venta")

    cliente_destino_id: uuid.UUID | None = None
    if cliente_nombre := data.get("cliente_nombre"):
        cliente = _find_or_create_cliente(db, str(cliente_nombre))
        cliente_destino_id = cliente.id

    payload = ChequeManualTransition(
        target_state=ChequeEstado.VENDIDO,
        operador_id=phone,
        motivo="Venta registrada por operador",
        porcentaje_venta=pct_venta,
        cliente_destino_id=cliente_destino_id,
    )
    cheque = svc_cheques.transition_cheque(db, objetivo.id, payload, event_at=msg_at)

    lines = [
        f"✅ *Cheque vendido*",
        f"Nº {cheque.nro_cheque}",
        f"Venta: {_pct(cheque.porcentaje_venta)}% | Compra: {_pct(cheque.porcentaje_compra)}%",
        f"Ganancia: {_ars(cheque.ganancia)}",
    ]
    # Venta por debajo del % de compra ⇒ pérdida. Se registra igual, solo avisamos.
    if cheque.ganancia is not None and cheque.ganancia < 0:
        lines.append("")
        lines.append(
            f"⚠️ *Venta a pérdida*: vendiste al {_pct(cheque.porcentaje_venta)}%, "
            f"por debajo del {_pct(cheque.porcentaje_compra)}% de compra."
        )
    return True, "\n".join(lines)


def _fiar_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    objetivo = _resolver_cheque(db, data)
    cliente_nombre = _req_str(data, "cliente_nombre")
    pct_venta = _req_decimal(data, "porcentaje_venta")

    cliente = _find_or_create_cliente(db, cliente_nombre)

    request = ChequeFiarRequest(
        operador_id=phone,
        motivo=f"Fiado a {cliente.nombre}",
        cliente_destino_id=cliente.id,
        porcentaje_venta=pct_venta,
    )
    cheque, fiado = svc_cheques.fiar_cheque(
        db, objetivo.id, request,
        fecha_fiado=fecha_local(msg_at),
        event_at=msg_at,
    )

    lines = [
        f"✅ *Cheque fiado*",
        f"Nº {cheque.nro_cheque} → {cliente.nombre}",
        f"Monto nominal: {_ars(cheque.monto)}",
        f"Descuento: {_pct(pct_venta)}% | Saldo pendiente: {_ars(fiado.saldo_pendiente)}",
    ]
    return True, "\n".join(lines)


def _cobrar_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    objetivo = _resolver_cheque(db, data)
    payload = ChequeManualTransition(
        target_state=ChequeEstado.COBRADO,
        operador_id=phone,
        motivo="Cobrado en ventanilla",
    )
    cheque = svc_cheques.transition_cheque(db, objetivo.id, payload, event_at=msg_at)
    return True, f"✅ Cheque Nº {cheque.nro_cheque} marcado como *COBRADO*."


def _rechazar_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    objetivo = _resolver_cheque(db, data)
    payload = ChequeManualTransition(
        target_state=ChequeEstado.RECHAZADO,
        operador_id=phone,
        motivo="Rechazado — informado por operador",
    )
    cheque = svc_cheques.transition_cheque(db, objetivo.id, payload, event_at=msg_at)
    return True, f"⛔ Cheque Nº {cheque.nro_cheque} marcado como *RECHAZADO*. Gestioná el recupero externamente."


def _nuevo_prestamo(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    credito = _req_decimal(data, "credito")
    moneda = _req_enum(data, "moneda", Moneda)
    cuotas = _req_int(data, "cuotas")
    frecuencia = _req_enum(data, "frecuencia", FrecuenciaCuotas)
    total = _req_decimal(data, "total_a_cobrar")

    cliente = _find_or_create_cliente(db, cliente_nombre)

    payload = PrestamoCreate(
        cliente_id=cliente.id,
        credito=credito,
        moneda=moneda,
        cuotas=cuotas,
        frecuencia=frecuencia,
        total_a_cobrar=total,
        fecha_inicio=fecha_local(msg_at),
    )
    prestamo = svc_prestamos.create_prestamo(db, payload)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    lines = [
        f"✅ *Préstamo registrado*",
        f"Cliente: {cliente.nombre}",
        f"Crédito: {simbolo}{_fmt_num(credito)} | Total: {simbolo}{_fmt_num(total)}",
        f"{cuotas} cuotas {_FRECUENCIA_PLURAL[frecuencia]}",
        f"Ganancia: {simbolo}{_fmt_num(prestamo.ganancia)}",
    ]
    return True, "\n".join(lines)


def _cobrar_cuota(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    numero_cuota: int | None = data.get("numero_cuota")
    try:
        cantidad = max(1, int(data.get("cantidad_cuotas") or 1))
    except (TypeError, ValueError):
        cantidad = 1

    cliente = _buscar_cliente_o_error(db, cliente_nombre, estricto=True)

    # Buscar cuotas por cobrar del cliente (PENDIENTE o EN_MORA).
    stmt = (
        select(Cuota)
        .join(Prestamo, Cuota.prestamo_id == Prestamo.id)
        .where(
            Prestamo.cliente_id == cliente.id,
            Prestamo.estado != PrestamoEstado.CANCELADO,
            Cuota.estado != CuotaEstado.COBRADA,
        )
        .order_by(Cuota.fecha_vencimiento.asc())
    )
    pendientes: list[Cuota] = list(db.scalars(stmt).all())

    if not pendientes:
        return False, f"ℹ️ {cliente.nombre} no tiene cuotas pendientes."

    if numero_cuota is not None:
        matches = [c for c in pendientes if c.numero_cuota == numero_cuota]
        if not matches:
            return False, (
                f"❓ No encontré la cuota #{numero_cuota} pendiente de {cliente.nombre}.\n"
                f"Cuotas pendientes: {', '.join(f'#{c.numero_cuota}' for c in pendientes)}"
            )
        if len(matches) > 1:
            # El cliente tiene varios préstamos activos con esa misma cuota.
            return False, (
                f"❓ {cliente.nombre} tiene {len(matches)} préstamos activos con una "
                f"cuota #{numero_cuota} pendiente. No puedo saber cuál cobrar; "
                "resolvelo desde el panel web."
            )
        cuota_inicial = matches[0]
    else:
        # Cobrar desde la primera (más próxima a vencer)
        cuota_inicial = pendientes[0]

    prestamo_id = cuota_inicial.prestamo_id
    prestamo_obj = db.get(Prestamo, prestamo_id)
    simbolo = "U$D" if prestamo_obj and prestamo_obj.moneda == Moneda.USD else "$"

    # Cuotas pendientes del MISMO préstamo, en orden de vencimiento, desde la inicial.
    del_prestamo = [c for c in pendientes if c.prestamo_id == prestamo_id]
    idx_inicial = del_prestamo.index(cuota_inicial)
    a_cobrar = del_prestamo[idx_inicial : idx_inicial + cantidad]

    fecha_cobro = fecha_local(msg_at)
    cobradas = [
        svc_prestamos.cobrar_cuota(db, prestamo_id, c.id, fecha_cobro=fecha_cobro)
        for c in a_cobrar
    ]

    restantes = len(del_prestamo) - len(cobradas)
    extra = (
        "\n✨ Préstamo *cancelado* — todas las cuotas cobradas."
        if restantes == 0
        else f"\nQuedan {restantes} cuota(s) pendiente(s) en este préstamo."
    )
    # Aviso si pidió más cuotas de las que había pendientes en este préstamo.
    if cantidad > len(cobradas):
        extra = (
            f"\n⚠️ Pediste cobrar {cantidad} pero solo había {len(cobradas)} "
            f"pendiente(s) en este préstamo." + extra
        )

    if len(cobradas) == 1:
        c = cobradas[0]
        return True, (
            f"✅ Cuota #{c.numero_cuota} de {cliente.nombre} cobrada.\n"
            f"Monto: {simbolo}{_fmt_num(c.monto)}{extra}"
        )

    nros = ", ".join(f"#{c.numero_cuota}" for c in cobradas)
    total_cobrado = sum((c.monto for c in cobradas), Decimal("0.00"))
    return True, (
        f"✅ Cobré {len(cobradas)} cuotas de {cliente.nombre} ({nros}).\n"
        f"Total: {simbolo}{_fmt_num(total_cobrado)}{extra}"
    )


def _registrar_deuda(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    """Alta de una deuda del negocio desde el chat (§5).

    `ingreso_caja` distingue los dos casos que se dicen parecido: la deuda comercial
    de siempre —que no mueve la caja— y la plata que le prestaron al negocio, que
    además entra al cajón. La respuesta dice cuál de los dos se anotó, para que el
    operador lo corrija en el momento si el bot leyó mal el mensaje."""
    acreedor = _req_str(data, "acreedor")
    concepto = _req_str(data, "concepto")
    monto = _req_decimal(data, "monto")
    moneda = _req_enum(data, "moneda", Moneda) if data.get("moneda") else Moneda.ARS
    fecha_vencimiento = _opt_date(data, "fecha_vencimiento")
    ingreso_caja = bool(data.get("ingreso_caja"))
    fecha_ingreso = _opt_date(data, "fecha_ingreso")
    # Solo si le prestaron dólares: el costo con el que entran al stock. El servicio
    # lo exige —sin lote no se pueden vender— y el prompt lo pide antes de llegar acá.
    cotizacion_ingreso = _opt_decimal(data, "cotizacion_ingreso_usd")

    payload = PasivoCreate(
        acreedor=acreedor,
        concepto=concepto,
        monto=monto,
        moneda=moneda,
        fecha_vencimiento=fecha_vencimiento,
        ingreso_caja=ingreso_caja,
        fecha_ingreso=fecha_ingreso,
        cotizacion_ingreso_usd=cotizacion_ingreso,
    )
    pasivo = svc_pasivos.create_pasivo(db, payload, created_at=msg_at)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    titulo = "💰 *Préstamo recibido*" if pasivo.ingreso_caja else "📋 *Deuda registrada*"
    lines = [
        titulo,
        f"Acreedor: {pasivo.acreedor}",
        f"Concepto: {pasivo.concepto}",
        f"Monto: {simbolo}{_fmt_num(monto)}",
    ]
    if pasivo.fecha_vencimiento:
        lines.append(f"Vencimiento: {_fmt_date(pasivo.fecha_vencimiento)}")
    if pasivo.ingreso_caja:
        lines.append(f"Entró a caja el {_fmt_date(pasivo.fecha_ingreso)}")
        if pasivo.cotizacion_ingreso_usd is not None:
            # Los dólares entran al stock a ese costo: es contra lo que se calcula
            # la ganancia si los vende, así que tiene que verlo al cargarlos.
            lines.append(
                f"Al stock a ${_fmt_num(pasivo.cotizacion_ingreso_usd)} — ya los podés vender"
            )
    else:
        lines.append("No mueve la caja (se descuenta cuando la pagues)")
    return True, "\n".join(lines)


def _registrar_deuda_cliente(
    db: Session, data: dict[str, Any], msg_at: datetime | None = None
) -> DispatchResult:
    """Alta de una deuda libre de un cliente desde el chat (§2.b).

    Es la dirección OPUESTA a `_registrar_deuda`, que anota lo que el negocio
    debe (un pasivo). Acá la plata salió: `create_deuda_simple` asienta el egreso
    `OTORGAMIENTO_DEUDA` del día. Por eso la respuesta dice explícitamente cuánto
    salió de caja — si el operador quiso anotar un pasivo, lo ve en el acto."""
    cliente_nombre = _req_str(data, "cliente_nombre")
    concepto = _req_str(data, "concepto")
    monto = _req_decimal(data, "monto")
    moneda = _req_enum(data, "moneda", Moneda) if data.get("moneda") else Moneda.ARS
    fecha = _opt_date(data, "fecha")

    cliente = _find_or_create_cliente(db, cliente_nombre)

    payload = DeudaSimpleCreate(
        cliente_id=cliente.id,
        concepto=concepto,
        monto=monto,
        moneda=moneda,
        fecha=fecha or fecha_local(msg_at),
    )
    deuda = svc_deudas_simples.create_deuda_simple(db, payload)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    lines = [
        "🧾 *Deuda de cliente registrada*",
        f"Cliente: {cliente.nombre} le debe al negocio",
        f"Concepto: {deuda.concepto}",
        f"Monto: {simbolo}{_fmt_num(monto)}",
        f"Salió de caja el {_fmt_date(deuda.fecha)}",
    ]
    return True, "\n".join(lines)


def _movimiento_efectivo(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    tipo = _req_enum(data, "tipo", MovimientoEfectivoTipo)
    moneda = _req_enum(data, "moneda", Moneda)
    monto = _req_decimal(data, "monto")
    cotizacion = _req_decimal(data, "cotizacion_aplicada")
    observaciones: str | None = data.get("observaciones")

    cliente_id: uuid.UUID | None = None
    if cliente_nombre := data.get("cliente_nombre"):
        cliente = _find_or_create_cliente(db, str(cliente_nombre))
        cliente_id = cliente.id

    # La ganancia NO se pasa: en la venta el servicio la calcula por lotes FIFO.
    # Comprada a deber: `monto_abonado` es lo que se pagó en el acto (0 si nada).
    # El schema exige el vendedor y rechaza que una venta quede a deber.
    monto_abonado = _opt_decimal(data, "monto_abonado")

    payload = MovimientoEfectivoCreate(
        cliente_id=cliente_id,
        tipo=tipo,
        moneda=moneda,
        monto=monto,
        cotizacion_aplicada=cotizacion,
        monto_abonado=monto_abonado,
        fecha_operacion=msg_at,
        observaciones=observaciones,
    )
    mov = svc_movimientos.create_movimiento(db, payload)

    accion = "Compra" if tipo == MovimientoEfectivoTipo.COMPRA else "Venta"
    lines = [
        f"✅ *{accion} de {moneda.value} registrada*",
        f"Monto: {_fmt_num(monto)} {moneda.value}",
        f"Cotización: ${_fmt_num(cotizacion)}",
    ]
    if tipo == MovimientoEfectivoTipo.VENTA and mov.ganancia is not None:
        signo = "Ganancia" if mov.ganancia >= 0 else "Pérdida"
        lines.append(f"{signo} (FIFO): {_ars(abs(mov.ganancia))}")
    # Cuánto salió de la caja es el control inmediato del operador: si el bot
    # entendió mal que la compra era a deber, el número lo delata en el acto.
    if tipo == MovimientoEfectivoTipo.COMPRA:
        pesos = (monto * cotizacion).quantize(Decimal("0.01"))
        abonado, a_deber = svc_pasivos.repartir_compra(pesos, monto_abonado)
        lines.append(f"Salió de caja: {_ars(abonado)}")
        if a_deber > 0:
            lines.append(f"⚠️ Queda a deber: {_ars(a_deber)}")
    return True, "\n".join(lines)


# Umbral de similitud de concepto (0..1) para considerar dos gastos "parecidos".
_GASTO_CONCEPTO_RATIO = 0.82


def _concepto_similar(a: str, b: str) -> bool:
    """True si dos conceptos son iguales, uno contiene al otro, o difieren por tipeo."""
    a, b = a.strip().lower(), b.strip().lower()
    if not a or not b:
        return False
    if a == b or a in b or b in a:
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= _GASTO_CONCEPTO_RATIO


def _monto_similar(m1: Decimal, m2: Decimal) -> bool:
    """True si dos montos son cercanos: difieren ≤ max($2.000, 20%) — cubre el típico
    error de tipeo de mil pesos. Montos muy distintos se asumen gastos legítimos."""
    if m1 == m2:
        return True
    mayor = max(m1, m2)
    tolerancia = max(Decimal("2000"), mayor * Decimal("0.20"))
    return abs(m1 - m2) <= tolerancia


def _gastos_parecidos_hoy(
    db: Session, concepto: str, monto: Decimal, moneda: Moneda, fecha: date
) -> list[GastoOperativo]:
    """Gastos ya registrados ESE día con concepto parecido y monto cercano."""
    deldia = list(
        db.scalars(
            select(GastoOperativo).where(
                GastoOperativo.fecha_operacion == fecha,
                GastoOperativo.moneda == moneda,
                GastoOperativo.anulado_at.is_(None),
            )
        ).all()
    )
    return [
        g for g in deldia
        if _concepto_similar(concepto, g.concepto) and _monto_similar(monto, g.monto)
    ]


def _registrar_gasto(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    # Acepta un gasto suelto (concepto/monto en la raíz) o varios en data["gastos"].
    items = data.get("gastos")
    if not isinstance(items, list) or not items:
        items = [data]

    fecha = fecha_local(msg_at)
    hora = hora_local(msg_at)

    # Parsear y validar TODO antes de tocar la BD.
    parsed: list[tuple[str, Decimal, Moneda]] = []
    for item in items:
        concepto = _req_str(item, "concepto")
        monto = _req_decimal(item, "monto")
        moneda = _req_enum(item, "moneda", Moneda) if item.get("moneda") else Moneda.ARS
        parsed.append((concepto, monto, moneda))

    # Detección de posible duplicado del día (salvo que el operador ya haya confirmado).
    if not data.get("_dup_confirmado"):
        avisos: list[str] = []
        for concepto, monto, moneda in parsed:
            similares = _gastos_parecidos_hoy(db, concepto, monto, moneda, fecha)
            for g in similares:
                simbolo = "U$D" if g.moneda == Moneda.USD else "$"
                hr = f" {g.hora_operacion.strftime('%H:%M')}" if g.hora_operacion else ""
                nuevo_simbolo = "U$D" if moneda == Moneda.USD else "$"
                avisos.append(
                    f"  • Ya hay «{g.concepto}» {simbolo}{_fmt_num(g.monto)}{hr} "
                    f"→ estás por cargar «{concepto}» {nuevo_simbolo}{_fmt_num(monto)}"
                )
        if avisos:
            raise ConfirmacionRequerida(
                "⚠️ *Posible gasto duplicado* (hoy ya cargaste algo parecido):\n"
                + "\n".join(avisos)
                + "\n\n¿Lo registro igual? Respondé *sí* para confirmar o *no* para descartar."
            )

    registrados = []
    for concepto, monto, moneda in parsed:
        gasto = svc_gastos.create_gasto(
            db,
            GastoOperativoCreate(
                concepto=concepto,
                monto=monto,
                moneda=moneda,
                fecha_operacion=fecha,
                hora_operacion=hora,
            ),
        )
        registrados.append(gasto)

    hora_txt = hora.strftime("%H:%M")
    if len(registrados) == 1:
        g = registrados[0]
        simbolo = "U$D" if g.moneda == Moneda.USD else "$"
        return True, (
            f"💸 *Gasto registrado* ({hora_txt})\n"
            f"Concepto: {g.concepto}\n"
            f"Monto: {simbolo}{_fmt_num(g.monto)}"
        )

    lines = [f"💸 *{len(registrados)} gastos registrados* ({hora_txt})"]
    total_por_moneda: dict[Moneda, Decimal] = {}
    for g in registrados:
        simbolo = "U$D" if g.moneda == Moneda.USD else "$"
        lines.append(f"  • {g.concepto}: {simbolo}{_fmt_num(g.monto)}")
        total_por_moneda[g.moneda] = total_por_moneda.get(g.moneda, Decimal("0.00")) + g.monto
    totales = " | ".join(
        f"{'U$D' if m == Moneda.USD else '$'}{_fmt_num(t)}" for m, t in total_por_moneda.items()
    )
    lines.append(f"*Total:* {totales}")
    return True, "\n".join(lines)


def _cobrar_fiado_efectivo(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    monto_cobrado = _req_decimal(data, "monto_cobrado")

    fiado = _buscar_fiado_abierto(db, cliente_nombre)
    if fiado is None:
        return False, f"❓ No encontré un fiado abierto para '{cliente_nombre}'."

    payload = FiadoCobrarEfectivoRequest(
        monto_cobrado=monto_cobrado,
        operador_id=phone,
    )
    fiado_actualizado = svc_fiados.cobrar_con_efectivo(db, fiado.id, payload)

    if fiado_actualizado.estado == FiadoEstado.CANCELADO:
        return True, (
            f"✅ *Fiado cancelado* — {cliente_nombre}\n"
            f"Cobrado: {_ars(monto_cobrado)}\n"
            f"🎉 Deuda saldada completamente."
        )
    return True, (
        f"✅ *Pago parcial registrado* — {cliente_nombre}\n"
        f"Cobrado: {_ars(monto_cobrado)}\n"
        f"Saldo restante: {_ars(fiado_actualizado.saldo_pendiente)}"
    )


def _cobrar_deuda_cliente(
    db: Session, data: dict[str, Any], msg_at: datetime | None = None
) -> DispatchResult:
    """Cobro consolidado: el cliente entregó plata contra lo que debe.

    Es el equivalente por chat del botón de la pestaña General: no se elige a
    qué deuda va —el importe se imputa de la operación más vieja a la más nueva,
    cruzando cheques fiados, deudas libres y cuotas de préstamo—. Para cobrar
    una deuda puntual están `COBRAR_CUOTA` y `COBRAR_FIADO_EFECTIVO`.

    **La moneda de la deuda se resuelve sola** cuando el operador no la aclara:
    si el cliente debe en una sola moneda, es esa. Si debe en las dos, se
    pregunta en vez de elegir — imputar pesos contra la deuda en dólares (o al
    revés) cambia el saldo de dos cajas distintas.
    """
    cliente_nombre = _req_str(data, "cliente_nombre")
    monto_cobrado = _req_decimal(data, "monto_cobrado")
    moneda_pago = _req_enum(data, "moneda_pago", Moneda) if data.get("moneda_pago") else Moneda.ARS
    cotizacion = _opt_decimal(data, "cotizacion")

    cliente = _buscar_cliente_o_error(db, cliente_nombre, estricto=True)

    ars = svc_deudores.resumen_cliente(db, cliente.id, Moneda.ARS)
    usd = svc_deudores.resumen_cliente(db, cliente.id, Moneda.USD)
    con_deuda = [r for r in (ars, usd) if r.total > Decimal("0.00")]
    if not con_deuda:
        return False, f"❓ {cliente.nombre} no tiene deuda abierta."

    if data.get("moneda_deuda"):
        moneda_deuda = _req_enum(data, "moneda_deuda", Moneda)
    elif len(con_deuda) == 1:
        moneda_deuda = con_deuda[0].moneda
    else:
        return False, (
            f"❓ {cliente.nombre} debe {_ars(ars.total)} y U$D{_fmt_num(usd.total)}. "
            "¿Contra cuál imputo el pago, la deuda en pesos o la de dólares?"
        )

    payload = CobroClienteCreate(
        cliente_id=cliente.id,
        moneda_deuda=moneda_deuda,
        monto_cobrado=monto_cobrado,
        moneda_pago=moneda_pago,
        cotizacion=cotizacion,
        fecha_cobro=fecha_local(msg_at),
    )
    r = svc_deudores.cobrar_cliente(db, payload)

    simbolo_pago = "U$D" if moneda_pago == Moneda.USD else "$"
    simbolo_deuda = "U$D" if moneda_deuda == Moneda.USD else "$"
    lines = [
        f"✅ *Cobro registrado* — {r.cliente_nombre}",
        f"Recibido: {simbolo_pago}{_fmt_num(monto_cobrado)}",
        "",
        "Se imputó a:",
    ]
    for renglon in r.renglones:
        saldado = " ✔️ saldado" if renglon.cancelado else ""
        lines.append(
            f"  • {renglon.detalle} — {simbolo_deuda}{_fmt_num(renglon.imputado)}{saldado}"
        )
    lines.append("")
    if r.saldo_restante <= Decimal("0.00"):
        lines.append(f"🎉 No debe más nada en {moneda_deuda.value}.")
    else:
        lines.append(f"Sigue debiendo: {simbolo_deuda}{_fmt_num(r.saldo_restante)}")
    return True, "\n".join(lines)


def _resolver_acreedor(db: Session, nombre: str) -> tuple[str, list[Pasivo]]:
    """Resuelve a qué acreedor le transfirieron y trae TODAS sus deudas vivas.

    El acreedor de un pasivo es **texto libre**, no un cliente del sistema (se
    le puede deber a alguien que nunca operó acá), así que se resuelve por
    nombre como los clientes: substring, y si coincide más de un acreedor se
    pregunta en vez de elegir — compensar contra el equivocado saldaría una
    deuda que sigue viva.

    Devuelve el nombre **exacto** tal como está guardado, porque es lo que el
    servicio usa para juntar sus deudas, y la lista completa: la transferencia
    se reparte entre todas, de la más vieja a la más nueva.
    """
    nombre = nombre.strip()
    candidatos: list[Pasivo] = list(
        db.scalars(
            select(Pasivo)
            .where(
                Pasivo.acreedor.ilike(f"%{nombre}%"),
                Pasivo.estado == PasivoEstado.PENDIENTE,
                Pasivo.saldo_pendiente > Decimal("0.00"),
                Pasivo.anulado_at.is_(None),
            )
            .order_by(Pasivo.created_at.asc())
        ).all()
    )
    if not candidatos:
        raise ValueError(
            f"No encontré ninguna deuda tuya con '{nombre}'. ¿A quién le "
            "transfirió exactamente?"
        )

    acreedores = {p.acreedor.strip().lower() for p in candidatos}
    if len(acreedores) > 1:
        nombres = ", ".join(sorted({p.acreedor for p in candidatos})[:5])
        raise ValueError(
            f"Le debés a varios que coinciden con '{nombre}': {nombres}. "
            "¿A cuál de todos le transfirió?"
        )
    return candidatos[0].acreedor, candidatos


def _compensar_deuda(
    db: Session, data: dict[str, Any], msg_at: datetime | None = None
) -> DispatchResult:
    """El cliente le transfirió a un acreedor del negocio: bajan las dos deudas.

    No es un cobro: la plata nunca entró a la caja. La respuesta lo dice
    explícitamente, porque es el control inmediato del operador de que el bot no
    confundió esto con "me pagó" —que sí haría entrar plata que no entró—.

    Igual que en el cobro consolidado, si el cliente debe en las dos monedas se
    pregunta en vez de elegir: imputar pesos contra la deuda en dólares mueve
    dos cajas distintas.
    """
    cliente_nombre = _req_str(data, "cliente_nombre")
    acreedor_nombre = _req_str(data, "acreedor_nombre")
    monto = _req_decimal(data, "monto")
    moneda = _req_enum(data, "moneda", Moneda) if data.get("moneda") else Moneda.ARS
    cotizacion = _opt_decimal(data, "cotizacion")

    cliente = _buscar_cliente_o_error(db, cliente_nombre, estricto=True)
    acreedor, pasivos = _resolver_acreedor(db, acreedor_nombre)
    # Si le debés en las dos monedas, elegir por su cuenta movería la caja
    # equivocada. Mismo criterio que con la deuda del cliente, abajo.
    monedas_pasivo = {p.moneda for p in pasivos}
    if data.get("moneda_pasivo"):
        moneda_pasivo = _req_enum(data, "moneda_pasivo", Moneda)
    elif len(monedas_pasivo) == 1:
        moneda_pasivo = next(iter(monedas_pasivo))
    else:
        return False, (
            f"❓ Le debés a {acreedor} en pesos y en dólares. "
            "¿Contra cuál de las dos imputo la transferencia?"
        )
    del pasivos  # el servicio las vuelve a cargar con bloqueo

    ars = svc_deudores.resumen_cliente(db, cliente.id, Moneda.ARS)
    usd = svc_deudores.resumen_cliente(db, cliente.id, Moneda.USD)
    con_deuda = [r for r in (ars, usd) if r.total > Decimal("0.00")]
    if not con_deuda:
        return False, f"❓ {cliente.nombre} no tiene deuda abierta."

    if data.get("moneda_deuda"):
        moneda_deuda = _req_enum(data, "moneda_deuda", Moneda)
    elif len(con_deuda) == 1:
        moneda_deuda = con_deuda[0].moneda
    else:
        return False, (
            f"❓ {cliente.nombre} debe {_ars(ars.total)} y U$D{_fmt_num(usd.total)}. "
            "¿Contra cuál imputo la transferencia, la deuda en pesos o la de dólares?"
        )

    payload = CompensacionCreate(
        cliente_id=cliente.id,
        acreedor=acreedor,
        moneda_pasivo=moneda_pasivo,
        moneda_deuda=moneda_deuda,
        monto=monto,
        moneda=moneda,
        cotizacion=cotizacion,
        fecha=fecha_local(msg_at),
    )
    r = svc_compensaciones.compensar(db, payload)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    simbolo_deuda = "U$D" if moneda_deuda == Moneda.USD else "$"
    simbolo_pasivo = "U$D" if moneda_pasivo == Moneda.USD else "$"
    lines = [
        f"✅ *Compensación registrada*",
        f"{r.cliente_nombre} le transfirió {simbolo}{_fmt_num(monto)} a {r.acreedor}",
        "⚠️ No movió la caja: esa plata no pasó por acá.",
        "",
        f"*{r.cliente_nombre} te debía* — se imputó a:",
    ]
    for renglon in r.renglones:
        saldado = " ✔️ saldado" if renglon.cancelado else ""
        lines.append(
            f"  • {renglon.detalle} — {simbolo_deuda}{_fmt_num(renglon.imputado)}{saldado}"
        )
    if r.saldo_restante_cliente <= Decimal("0.00"):
        lines.append(f"  🎉 No te debe más nada en {moneda_deuda.value}.")
    else:
        lines.append(f"  Sigue debiendo: {simbolo_deuda}{_fmt_num(r.saldo_restante_cliente)}")

    lines.append("")
    lines.append(f"*Le debías a {r.acreedor}*:")
    lines.append(f"  • Se descontó: {simbolo_pasivo}{_fmt_num(r.imputado_pasivo)}")
    if r.pasivos_cancelados:
        plural = "s" if r.pasivos_cancelados > 1 else ""
        lines.append(f"  ✔️ {r.pasivos_cancelados} deuda{plural} saldada{plural}")
    if r.saldo_restante_pasivo <= Decimal("0.00"):
        lines.append("  🎉 No le debés más nada.")
    else:
        lines.append(f"  Le seguís debiendo: {simbolo_pasivo}{_fmt_num(r.saldo_restante_pasivo)}")

    if r.excedente > Decimal("0.00"):
        lines.append("")
        lines.append(
            f"↩️ Transfirió {simbolo}{_fmt_num(r.excedente)} de más: "
            f"le quedan a favor (ahora se los debés vos)."
        )
    return True, "\n".join(lines)


def _cobrar_fiado_con_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    nro_cheque_pago = _req_str(data, "nro_cheque_pago")
    banco_pago = (str(data["banco_pago"]).strip() or None) if data.get("banco_pago") else None
    monto_cheque = _req_decimal(data, "monto_cheque")
    pct_compra = _req_decimal(data, "porcentaje_compra_cheque")
    fecha_emision = _opt_date(data, "fecha_emision")
    fecha_pago = _opt_date(data, "fecha_pago")

    fiado = _buscar_fiado_abierto(db, cliente_nombre)
    if fiado is None:
        return False, f"❓ No encontré un fiado abierto para '{cliente_nombre}'."

    payload = FiadoCobrarConChequeRequest(
        nro_cheque_pago=nro_cheque_pago,
        banco_pago=banco_pago,
        monto_cheque=monto_cheque,
        porcentaje_compra_cheque=pct_compra,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        operador_id=phone,
    )
    resultado = svc_fiados.cobrar_con_cheque(db, fiado.id, payload, created_at=msg_at)

    fiado_act = resultado.fiado
    diferencia = resultado.diferencia
    cheque_nuevo = resultado.cheque_ingresado

    lines = [
        f"✅ *Cheque recibido como pago de fiado* — {cliente_nombre}",
        f"Cheque Nº {cheque_nuevo.nro_cheque} | Nominal: {_ars(monto_cheque)} | Compra: {_pct(pct_compra)}%",
        f"Valor neto: {_ars(monto_cheque * (100 - pct_compra) / 100)}",
    ]

    if fiado_act.estado == FiadoEstado.CANCELADO:
        lines.append(f"🎉 Fiado *cancelado* — deuda saldada.")
        if diferencia > 0:
            lines.append(f"⚠️ El negocio queda debiendo al cliente: {_ars(diferencia)}")
    else:
        lines.append(f"Saldo restante del fiado: {_ars(fiado_act.saldo_pendiente)}")

    return True, "\n".join(lines)


def _buscar_fiado_abierto(db: Session, cliente_nombre: str) -> Fiado | None:
    """Devuelve el fiado ABIERTO del cliente.

    Returns None si el cliente existe pero no tiene fiados abiertos.
    Raises ValueError si el cliente no existe, hay ambigüedad de nombre,
    o hay múltiples fiados abiertos.
    """
    cliente = _buscar_cliente_o_error(db, cliente_nombre, estricto=True)
    fiados: list[Fiado] = list(
        db.scalars(
            select(Fiado).where(
                Fiado.cliente_id == cliente.id,
                Fiado.estado == FiadoEstado.ABIERTO,
                Fiado.anulado_at.is_(None),
            )
        ).all()
    )
    if len(fiados) == 1:
        return fiados[0]
    if len(fiados) > 1:
        raise ValueError(
            f"{cliente.nombre} tiene {len(fiados)} fiados abiertos. "
            "Contactá al administrador para resolverlo desde el panel."
        )
    return None


def _revertir_operacion(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    """Deshace una operación desde el chat (intent `REVERTIR_OPERACION`).

    Dos acciones sobre el mismo motor (`svc_anulacion`, ver §Anulación y reversión):
      - REVERTIR: solo cheques. Los devuelve a EN_CARTERA sin eliminarlos, para
        que se puedan volver a vender. Se borra el ingreso de la venta/cobro y se
        conserva el egreso de la compra, que sigue siendo cierto.
      - ELIMINAR: anula la operación entera y revierte su rastro en la caja.

    El bot resuelve la entidad por el identificador que dio el operador (número de
    cheque, "ultimo", nombre de cliente) y delega toda la validación al motor: las
    reglas de bloqueo son las mismas que en el panel, así que un fiado con cobros
    encima o una venta de USD que no es la última se rechazan igual acá.
    """
    accion = str(data.get("accion", "ELIMINAR")).upper().strip()
    tipo = str(data.get("tipo_operacion", "")).upper().strip()
    identificador = str(data.get("identificador", "")).strip()
    motivo = str(data.get("motivo") or "").strip() or "Revertido desde el chat"

    if not tipo:
        return False, "⚠️ No entendí qué operación querés deshacer."

    # ── Revertir un cheque a cartera ──────────────────────────────────
    if accion == "REVERTIR":
        if tipo != "CHEQUE":
            return False, (
                "⚠️ Solo los cheques se pueden volver a cartera. "
                "Para el resto, pedime que lo elimine."
            )
        cheque = svc_cheques.resolve_cheque(db, identificador)
        svc_anulacion.revertir_cheque(db, cheque.id, operador_id=phone, motivo=motivo)
        return True, (
            f"↩️ Cheque Nº {cheque.nro_cheque} de vuelta EN CARTERA.\n"
            f"Se sacó de la caja el ingreso de esa operación; el egreso de cuando "
            f"lo compraste se mantiene."
        )

    # ── Eliminar (anular) la operación ────────────────────────────────
    entidad, obj = _resolver_para_anular(db, tipo, identificador)
    impacto = svc_anulacion.anular(
        db, entidad, obj.id, operador_id=phone, motivo=motivo
    )

    detalle = ""
    if impacto.lineas:
        movs = "\n".join(
            f"  • {l.tipo} {l.moneda} {l.monto:,.2f} — {l.detalle or l.categoria}"
            for l in impacto.lineas[:5]
        )
        detalle = f"\nSe revirtió de la caja:\n{movs}"
        if len(impacto.lineas) > 5:
            detalle += f"\n  … y {len(impacto.lineas) - 5} movimiento(s) más."
    else:
        detalle = "\nNo movía plata, así que la caja no cambia."

    arrastre = ""
    if impacto.arrastra:
        arrastre = "\nTambién se dio de baja: " + ", ".join(impacto.arrastra)

    return True, f"🗑️ Eliminado: {impacto.descripcion}{detalle}{arrastre}"


def _resolver_para_anular(db: Session, tipo: str, identificador: str):
    """Traduce lo que dijo el operador a (entidad_del_motor, fila)."""
    ident = identificador.lower().strip()

    if tipo == "CHEQUE":
        return "cheque", svc_cheques.resolve_cheque(db, identificador)

    if tipo == "GASTO":
        gasto, error = _resolver_gasto_a_editar(db, identificador)
        if gasto is None:
            raise ValueError(error or "No encontré ese gasto.")
        return "gasto", gasto

    if tipo == "MOVIMIENTO":
        mov = db.scalars(
            select(MovimientoEfectivo)
            .where(MovimientoEfectivo.anulado_at.is_(None))
            .order_by(MovimientoEfectivo.created_at.desc())
            .limit(1)
        ).first()
        if mov is None:
            raise ValueError("No hay ninguna operación de divisas registrada.")
        return "movimiento_efectivo", mov

    if tipo == "PASIVO":
        if ident in ("ultimo", "último"):
            pasivo = db.scalars(
                select(Pasivo)
                .where(Pasivo.anulado_at.is_(None))
                .order_by(Pasivo.created_at.desc())
                .limit(1)
            ).first()
        else:
            candidatos = list(
                db.scalars(
                    select(Pasivo).where(
                        Pasivo.acreedor.ilike(f"%{identificador}%"),
                        Pasivo.anulado_at.is_(None),
                    )
                ).all()
            )
            if len(candidatos) > 1:
                nombres = ", ".join(p.acreedor for p in candidatos[:5])
                raise ValueError(
                    f"Hay {len(candidatos)} deudas que coinciden ({nombres}). "
                    "Decime cuál con más precisión."
                )
            pasivo = candidatos[0] if candidatos else None
        if pasivo is None:
            raise ValueError("No encontré esa deuda.")
        return "pasivo", pasivo

    if tipo == "PRESTAMO":
        cliente = _buscar_cliente_o_error(db, identificador, estricto=True)
        prestamos = list(
            db.scalars(
                select(Prestamo).where(
                    Prestamo.cliente_id == cliente.id,
                    Prestamo.anulado_at.is_(None),
                )
                .order_by(Prestamo.created_at.desc())
            ).all()
        )
        if not prestamos:
            raise ValueError(f"{cliente.nombre} no tiene préstamos cargados.")
        if len(prestamos) > 1:
            raise ValueError(
                f"{cliente.nombre} tiene {len(prestamos)} préstamos. "
                "Eliminá el que corresponda desde el panel para no equivocarnos."
            )
        return "prestamo", prestamos[0]

    if tipo == "COMPENSACION":
        # Por cliente, o "ultimo". Una compensación no tiene número propio que el
        # operador recuerde: la identifica por quién transfirió.
        stmt = select(Compensacion).where(Compensacion.anulado_at.is_(None))
        if ident not in ("ultimo", "último", ""):
            cliente = _buscar_cliente_o_error(db, identificador, estricto=True)
            stmt = stmt.where(Compensacion.cliente_id == cliente.id)
        comp = db.scalars(stmt.order_by(Compensacion.created_at.desc()).limit(1)).first()
        if comp is None:
            raise ValueError("No encontré ninguna compensación para deshacer.")
        return "compensacion", comp

    raise ValueError(f"No sé deshacer operaciones de tipo '{tipo}'.")


def _editar_operacion(db: Session, data: dict[str, Any]) -> DispatchResult:
    tipo = str(data.get("tipo_operacion", "")).upper().strip()
    identificador = str(data.get("identificador", "")).strip()
    campo = str(data.get("campo", "")).lower().strip()
    nuevo_valor = data.get("nuevo_valor")

    if not campo:
        return False, "⚠️ No entendí qué campo querés corregir."
    if nuevo_valor is None:
        return False, "⚠️ No entendí el nuevo valor."

    if tipo == "CHEQUE":
        return _editar_cheque(db, identificador, campo, nuevo_valor)
    if tipo == "MOVIMIENTO":
        return _editar_movimiento(db, identificador, campo, nuevo_valor)
    if tipo == "GASTO":
        return _editar_gasto(
            db, identificador, campo, nuevo_valor,
            monto_ref=data.get("monto_referencia"),
            hora_ref=data.get("hora_referencia"),
        )
    if tipo == "PASIVO":
        return _editar_pasivo(db, identificador, campo, nuevo_valor)
    return False, f"⚠️ Tipo de operación no reconocido: '{tipo}'."


_CIEN_PCT = Decimal("100")


def _resync_caja_cheque(db: Session, cheque: Cheque) -> None:
    """Reconstruye el rastro de caja de un cheque desde su estado actual.

    Se usa tras editar monto/%compra/%venta: borra las líneas de caja del cheque
    y las vuelve a crear (egreso de compra siempre; ingreso de venta/cobro según estado).
    """
    svc_caja.borrar_por_referencia(db, "cheque", cheque.id)
    pagado = (cheque.monto * (_CIEN_PCT - cheque.porcentaje_compra) / _CIEN_PCT).quantize(Decimal("0.01"))
    # La cartera preexistente nunca asentó el egreso de compra (ver
    # services/apertura.py): al resincronizar no hay que inventarlo.
    if pagado > 0 and not cheque.es_carga_inicial:
        svc_caja.registrar(
            db, fecha=fecha_local(cheque.created_at), moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.COMPRA_CHEQUE, monto=pagado,
            referencia_tipo="cheque", referencia_id=cheque.id,
            detalle=f"Compra cheque Nº {cheque.nro_cheque}",
        )
    if cheque.estado == ChequeEstado.VENDIDO and cheque.porcentaje_venta is not None:
        ingreso = (cheque.monto * (_CIEN_PCT - cheque.porcentaje_venta) / _CIEN_PCT).quantize(Decimal("0.01"))
        if ingreso > 0:
            svc_caja.registrar(
                db, fecha=fecha_local(cheque.ultimo_evento_manual_at), moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
                categoria=CajaCategoria.VENTA_CHEQUE, monto=ingreso,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=f"Venta cheque Nº {cheque.nro_cheque}",
            )
    elif cheque.estado == ChequeEstado.COBRADO:
        svc_caja.registrar(
            db, fecha=fecha_local(cheque.ultimo_evento_manual_at), moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
            categoria=CajaCategoria.COBRO_CHEQUE, monto=cheque.monto.quantize(Decimal("0.01")),
            referencia_tipo="cheque", referencia_id=cheque.id,
            detalle=f"Cobro cheque Nº {cheque.nro_cheque}",
        )


def _resync_caja_gasto(db: Session, gasto: GastoOperativo) -> None:
    """Reconstruye la línea de caja (egreso) de un gasto tras editar su monto/moneda."""
    svc_caja.borrar_por_referencia(db, "gasto", gasto.id)
    svc_caja.registrar(
        db, fecha=gasto.fecha_operacion, moneda=gasto.moneda, tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.GASTO, monto=gasto.monto,
        referencia_tipo="gasto", referencia_id=gasto.id, detalle=gasto.concepto,
    )


def _editar_cheque(db: Session, nro: str, campo: str, nuevo_valor: Any) -> DispatchResult:
    try:
        cheque = svc_cheques.resolve_cheque(db, nro)
    except ServiceError as exc:
        return False, f"⚠️ {exc.message}"
    nro = cheque.nro_cheque

    # Campos disponibles según el estado del cheque
    campos_base = {"monto", "porcentaje_compra", "fecha_emision", "fecha_pago", "cliente_origen"}
    campos_post = {"porcentaje_venta", "cliente_destino"}
    tiene_venta = cheque.estado in (ChequeEstado.VENDIDO, ChequeEstado.FIADO)
    campos_validos = campos_base | (campos_post if tiene_venta else set())

    if campo not in campos_validos:
        return False, (
            f"⚠️ Campo inválido: '{campo}'. "
            f"Para cheques {cheque.estado.value} podés corregir: {', '.join(sorted(campos_validos))}."
        )

    estado_tag = f" _{cheque.estado.value}_" if cheque.estado != ChequeEstado.EN_CARTERA else ""
    notas: list[str] = []

    if campo == "monto":
        nuevo = _parse_decimal_val(nuevo_valor)
        anterior = _ars(cheque.monto)
        cheque.monto = nuevo
        if cheque.estado == ChequeEstado.VENDIDO and cheque.porcentaje_venta is not None:
            cheque.ganancia = (nuevo * (cheque.porcentaje_compra - cheque.porcentaje_venta) / Decimal("100")).quantize(Decimal("0.01"))
            notas.append(f"Ganancia recalculada: {_ars(cheque.ganancia)}")
        if cheque.estado == ChequeEstado.FIADO and cheque.fiado_originado and cheque.fiado_originado.estado == FiadoEstado.ABIERTO:
            f = cheque.fiado_originado
            f.monto_original = nuevo
            f.saldo_pendiente = (nuevo * (Decimal("100") - f.porcentaje_venta) / Decimal("100")).quantize(Decimal("0.01"))
            notas.append(f"Fiado recalculado — saldo pendiente: {_ars(f.saldo_pendiente)}")
        _resync_caja_cheque(db, cheque)
        db.commit()
        resp = f"✅ *Cheque Nº {nro}*{estado_tag} — monto corregido.\n{anterior} → {_ars(nuevo)}"
        return True, resp + ("\n" + "\n".join(notas) if notas else "")

    if campo == "porcentaje_compra":
        nuevo = _parse_decimal_val(nuevo_valor)
        anterior = _pct(cheque.porcentaje_compra)
        cheque.porcentaje_compra = nuevo
        if cheque.estado == ChequeEstado.VENDIDO and cheque.porcentaje_venta is not None:
            cheque.ganancia = (cheque.monto * (nuevo - cheque.porcentaje_venta) / Decimal("100")).quantize(Decimal("0.01"))
            notas.append(f"Ganancia recalculada: {_ars(cheque.ganancia)}")
        _resync_caja_cheque(db, cheque)
        db.commit()
        resp = f"✅ *Cheque Nº {nro}*{estado_tag} — % compra corregido.\n{anterior}% → {_pct(nuevo)}%"
        return True, resp + ("\n" + "\n".join(notas) if notas else "")

    if campo == "porcentaje_venta":
        nuevo = _parse_decimal_val(nuevo_valor)
        anterior = _pct(cheque.porcentaje_venta) if cheque.porcentaje_venta is not None else "—"
        cheque.porcentaje_venta = nuevo
        if cheque.estado == ChequeEstado.VENDIDO:
            cheque.ganancia = (cheque.monto * (cheque.porcentaje_compra - nuevo) / Decimal("100")).quantize(Decimal("0.01"))
            notas.append(f"Ganancia recalculada: {_ars(cheque.ganancia)}")
        if cheque.estado == ChequeEstado.FIADO and cheque.fiado_originado and cheque.fiado_originado.estado == FiadoEstado.ABIERTO:
            f = cheque.fiado_originado
            f.porcentaje_venta = nuevo
            f.saldo_pendiente = (cheque.monto * (Decimal("100") - nuevo) / Decimal("100")).quantize(Decimal("0.01"))
            notas.append(f"Fiado recalculado — saldo pendiente: {_ars(f.saldo_pendiente)}")
        _resync_caja_cheque(db, cheque)
        db.commit()
        resp = f"✅ *Cheque Nº {nro}*{estado_tag} — % venta corregido.\n{anterior}% → {_pct(nuevo)}%"
        return True, resp + ("\n" + "\n".join(notas) if notas else "")

    if campo == "fecha_emision":
        nuevo_d = _parse_date_val(nuevo_valor)
        anterior = _fmt_date(cheque.fecha_emision)
        cheque.fecha_emision = nuevo_d
        db.commit()
        return True, f"✅ *Cheque Nº {nro}*{estado_tag} — fecha emisión corregida.\n{anterior} → {_fmt_date(nuevo_d)}"

    if campo == "fecha_pago":
        nuevo_d = _parse_date_val(nuevo_valor)
        anterior = _fmt_date(cheque.fecha_pago)
        cheque.fecha_pago = nuevo_d
        db.commit()
        return True, f"✅ *Cheque Nº {nro}*{estado_tag} — fecha de pago corregida.\n{anterior} → {_fmt_date(nuevo_d)}"

    if campo == "cliente_origen":
        cliente = _find_or_create_cliente(db, str(nuevo_valor))
        anterior = cheque.cliente_origen.nombre if cheque.cliente_origen else "—"
        cheque.cliente_origen_id = cliente.id
        db.commit()
        return True, f"✅ *Cheque Nº {nro}*{estado_tag} — origen corregido.\n{anterior} → {cliente.nombre}"

    if campo == "cliente_destino":
        cliente = _find_or_create_cliente(db, str(nuevo_valor))
        anterior = cheque.cliente_destino.nombre if cheque.cliente_destino else "—"
        cheque.cliente_destino_id = cliente.id
        db.commit()
        return True, f"✅ *Cheque Nº {nro}*{estado_tag} — destino corregido.\n{anterior} → {cliente.nombre}"

    return False, "⚠️ Error inesperado al editar el cheque."


def _editar_movimiento(db: Session, identificador: str, campo: str, nuevo_valor: Any) -> DispatchResult:
    # Editar una operación de divisas rompería la imputación FIFO de lotes y el libro
    # de caja (el stock de USD y la ganancia se calculan en cadena). No se edita desde
    # el chat: se corrige cargando una operación nueva que compense.
    return False, (
        "⚠️ Las operaciones de divisas no se editan desde el chat: afectan el stock "
        "de dólares (FIFO) y la caja. Si te equivocaste, registrá una operación nueva "
        "que lo corrija (ej. una venta/compra inversa)."
    )


_GASTO_ULTIMO_ALIASES = {"ultimo", "último", "el ultimo", "el último", "lo de recien", "lo de recién", ""}


def _parse_hora_ref(ref: Any) -> tuple[int, int | None] | None:
    """Interpreta una referencia de hora ('21:17', '21', '9 hs') → (hora, minuto|None)."""
    if ref is None:
        return None
    texto = str(ref).strip().lower().replace("hs", "").replace("h", "").replace(".", ":")
    partes = [p.strip() for p in texto.split(":") if p.strip()]
    if not partes or not partes[0].isdigit():
        return None
    hora = int(partes[0])
    minuto = int(partes[1]) if len(partes) > 1 and partes[1].isdigit() else None
    if not (0 <= hora <= 23):
        return None
    return hora, minuto


def _hora_coincide(hora_op: Any, ref: tuple[int, int | None]) -> bool:
    """True si la hora del gasto coincide con la referencia. Si la ref no trae minuto,
    coincide por hora; si lo trae, exige hora y minuto exactos."""
    if hora_op is None:
        return False
    hora, minuto = ref
    if hora_op.hour != hora:
        return False
    return minuto is None or hora_op.minute == minuto


def _resolver_gasto_a_editar(
    db: Session, identificador: str, monto_ref: Any = None, hora_ref: Any = None
) -> tuple[GastoOperativo | None, str | None]:
    """Resuelve qué gasto (de HOY) editar. Devuelve (gasto, mensaje_de_error).

    - "ultimo"/"el último" sin selectores → el más reciente.
    - concepto → gastos de hoy con concepto parecido.
    - monto_referencia / hora_referencia → afinan la selección ("el de 5000",
      "el de las 21:17"). Si igual quedan varios, pide desambiguar.
    """
    ident = identificador.strip().lower()
    usar_ultimo = ident in _GASTO_ULTIMO_ALIASES
    hora_parsed = _parse_hora_ref(hora_ref)
    monto_parsed: Decimal | None = None
    if monto_ref is not None:
        try:
            monto_parsed = _parse_decimal_val(monto_ref)
        except (ValueError, InvalidOperation):
            monto_parsed = None

    # Atajo: "el último" sin ningún selector adicional.
    if usar_ultimo and monto_parsed is None and hora_parsed is None:
        gasto = db.scalars(
            select(GastoOperativo)
            .where(GastoOperativo.anulado_at.is_(None))
            .order_by(GastoOperativo.created_at.desc())
            .limit(1)
        ).first()
        if gasto is None:
            return None, "❓ No encontré ningún gasto registrado."
        if gasto.fecha_operacion != hoy_local():
            return None, "❓ El último gasto no es de hoy. Editá días anteriores desde el panel web."
        return gasto, None

    # Universo: gastos de HOY (días anteriores solo se editan desde el panel).
    candidatos = list(
        db.scalars(
            select(GastoOperativo)
            .where(
                GastoOperativo.fecha_operacion == hoy_local(),
                GastoOperativo.anulado_at.is_(None),
            )
            .order_by(GastoOperativo.created_at.desc())
        ).all()
    )
    if not usar_ultimo and ident:
        candidatos = [g for g in candidatos if _concepto_similar(identificador, g.concepto)]
    if monto_parsed is not None:
        candidatos = [g for g in candidatos if g.monto == monto_parsed]
    if hora_parsed is not None:
        candidatos = [g for g in candidatos if _hora_coincide(g.hora_operacion, hora_parsed)]

    referencia = identificador if not usar_ultimo and ident else "ese gasto"
    if not candidatos:
        return None, (
            f"❓ No encontré un gasto de «{referencia}» hoy con esos datos. "
            "Revisá la hora/monto o corregilo desde el panel web."
        )
    if len(candidatos) == 1:
        return candidatos[0], None

    # Siguen siendo varios: listar para que el operador desambigüe por hora o monto.
    lineas = []
    for g in candidatos:
        simbolo = "U$D" if g.moneda == Moneda.USD else "$"
        hr = f" a las {g.hora_operacion.strftime('%H:%M')}" if g.hora_operacion else ""
        lineas.append(f"  • {g.concepto}: {simbolo}{_fmt_num(g.monto)}{hr}")
    return None, (
        f"❓ Hoy tenés {len(candidatos)} gastos parecidos:\n"
        + "\n".join(lineas)
        + "\n\nDecime cuál: por la hora (\"el de las 21:17\") o por el monto (\"el de 5000\")."
    )


def _editar_gasto(
    db: Session,
    identificador: str,
    campo: str,
    nuevo_valor: Any,
    monto_ref: Any = None,
    hora_ref: Any = None,
) -> DispatchResult:
    gasto, error = _resolver_gasto_a_editar(db, identificador, monto_ref, hora_ref)
    if error is not None:
        return False, error
    assert gasto is not None  # garantizado por el contrato de _resolver_gasto_a_editar

    campos_validos = {"concepto", "monto", "moneda"}
    if campo not in campos_validos:
        return False, (
            f"⚠️ Campo inválido: '{campo}'. "
            f"Para gastos podés corregir: concepto, monto, moneda."
        )

    if campo == "concepto":
        anterior = gasto.concepto
        gasto.concepto = str(nuevo_valor).strip()
        db.commit()
        return True, f"✅ *Gasto* — concepto corregido.\n'{anterior}' → '{gasto.concepto}'"

    if campo == "moneda":
        try:
            nueva_moneda = Moneda(str(nuevo_valor).upper())
        except ValueError:
            return False, f"⚠️ Moneda inválida: '{nuevo_valor}'. Válidas: ARS, USD."
        anterior = gasto.moneda.value
        gasto.moneda = nueva_moneda
        _resync_caja_gasto(db, gasto)
        db.commit()
        return True, f"✅ *Gasto '{gasto.concepto}'* — moneda corregida.\n{anterior} → {nueva_moneda.value}"

    nuevo = _parse_decimal_val(nuevo_valor)
    simbolo = "$" if gasto.moneda == Moneda.ARS else "U$D"
    anterior = f"{simbolo}{_fmt_num(gasto.monto)}"
    gasto.monto = nuevo
    _resync_caja_gasto(db, gasto)
    db.commit()
    return True, f"✅ *Gasto '{gasto.concepto}'* — monto corregido.\n{anterior} → {simbolo}{_fmt_num(nuevo)}"


def _editar_pasivo(db: Session, identificador: str, campo: str, nuevo_valor: Any) -> DispatchResult:
    if identificador.lower() == "ultimo":
        pasivo = db.scalars(
            select(Pasivo)
            .where(
                Pasivo.estado == PasivoEstado.PENDIENTE,
                Pasivo.anulado_at.is_(None),
            )
            .order_by(Pasivo.created_at.desc())
            .limit(1)
        ).first()
    else:
        # Buscar por nombre de acreedor
        resultados: list[Pasivo] = list(
            db.scalars(
                select(Pasivo).where(
                    Pasivo.acreedor.ilike(f"%{identificador}%"),
                    Pasivo.estado == PasivoEstado.PENDIENTE,
                    Pasivo.anulado_at.is_(None),
                )
            ).all()
        )
        pasivo = resultados[0] if len(resultados) == 1 else None
        if pasivo is None and resultados:
            nombres = ", ".join(f"{p.acreedor} (${_fmt_num(p.monto)})" for p in resultados[:3])
            return False, f"❓ Encontré varios pasivos con '{identificador}': {nombres}. Sé más específico."

    if pasivo is None:
        return False, f"❓ No encontré ningún pasivo pendiente para '{identificador}'."

    campos_validos = {
        "acreedor", "concepto", "monto", "moneda", "fecha_vencimiento", "ingreso_caja",
    }
    if campo not in campos_validos:
        return False, (
            f"⚠️ Campo inválido: '{campo}'. "
            f"Para pasivos podés corregir: {', '.join(sorted(campos_validos))}."
        )

    # "Esa plata me la prestaron" / "no, no entró plata": corrige si el alta debía
    # asentar el ingreso. Es el error más caro de esta operación —la caja del día
    # queda corta o larga por el monto entero— y se arregla desde el mismo chat.
    if campo == "ingreso_caja":
        entro = _parse_bool_val(nuevo_valor)
        acreedor_txt = pasivo.acreedor
        svc_pasivos.editar_pasivo(db, pasivo.id, PasivoUpdate(ingreso_caja=entro))
        estado = "Entró a caja" if entro else "No mueve la caja"
        return True, f"✅ *Pasivo con {acreedor_txt}* — corregido.\n{estado}"

    # Toda corrección pasa por el servicio: es el que recalcula el saldo al cambiar
    # el monto y el que rehace la línea de caja si esa deuda trajo plata (§5).
    # Escribir los campos a mano acá dejaba el saldo con el monto viejo.
    if campo in ("acreedor", "concepto"):
        anterior = getattr(pasivo, campo)
        nuevo_txt = str(nuevo_valor).strip()
        svc_pasivos.editar_pasivo(db, pasivo.id, PasivoUpdate(**{campo: nuevo_txt}))
        return True, f"✅ *Pasivo* — {campo} corregido.\n'{anterior}' → '{nuevo_txt}'"

    if campo == "monto":
        nuevo = _parse_decimal_val(nuevo_valor)
        simbolo = "$" if pasivo.moneda == Moneda.ARS else "U$D"
        anterior = f"{simbolo}{_fmt_num(pasivo.monto)}"
        acreedor_txt = pasivo.acreedor
        svc_pasivos.editar_pasivo(db, pasivo.id, PasivoUpdate(monto=nuevo))
        return True, (
            f"✅ *Pasivo con {acreedor_txt}* — monto corregido.\n"
            f"{anterior} → {simbolo}{_fmt_num(nuevo)}"
        )

    if campo == "moneda":
        try:
            nueva_moneda = Moneda(str(nuevo_valor).upper())
        except ValueError:
            return False, f"⚠️ Moneda inválida: '{nuevo_valor}'. Válidas: ARS, USD."
        anterior = pasivo.moneda.value
        acreedor_txt = pasivo.acreedor
        svc_pasivos.editar_pasivo(db, pasivo.id, PasivoUpdate(moneda=nueva_moneda))
        return True, (
            f"✅ *Pasivo con {acreedor_txt}* — moneda corregida.\n"
            f"{anterior} → {nueva_moneda.value}"
        )

    # campo == "fecha_vencimiento"
    nuevo_d = _parse_date_val(nuevo_valor)
    anterior = _fmt_date(pasivo.fecha_vencimiento)
    acreedor_txt = pasivo.acreedor
    svc_pasivos.editar_pasivo(db, pasivo.id, PasivoUpdate(fecha_vencimiento=nuevo_d))
    return True, (
        f"✅ *Pasivo con {acreedor_txt}* — vencimiento corregido.\n"
        f"{anterior} → {_fmt_date(nuevo_d)}"
    )


# Cuántas líneas de detalle entran en una respuesta antes de cortar. Un mes de
# movimientos o una cartera de 200 cheques no se leen en un celular: van los
# totales completos —que es lo que el operador pregunta— y las primeras líneas,
# con el resto contado al pie para que se note que hay más.
_MAX_DETALLE = 12

# Fecha desde la que se cuenta "TODO". Anterior a cualquier operación del
# sistema, y lo bastante concreta como para no pelearse con `date.min` en las
# comparaciones de Postgres.
_ORIGEN = date(2000, 1, 1)

# Consultas de FLUJO (lo que pasó en un período). El resto son de STOCK: una foto
# de cómo están las cosas ahora, donde el período no significa nada.
_CONSULTAS_DE_FLUJO = frozenset({"MOVIMIENTOS", "CAJA", "GASTOS", "VENTAS", "DIVISAS"})

# Intents del contrato anterior (uno por consulta) → su `tipo` de hoy.
_CONSULTAS_LEGACY = {
    "CONSULTA_CARTERA":   "CARTERA",
    "CONSULTA_CLIENTE":   "CLIENTE",
    "CONSULTA_PRESTAMOS": "PRESTAMOS",
}


def _resolver_periodo(
    data: dict[str, Any], *, hoy: date | None = None
) -> tuple[str, date, date]:
    """Traduce el período simbólico del modelo a fechas concretas.

    **El modelo no resuelve fechas, las nombra.** El system prompt está cacheado
    por prefijo y no puede llevar la fecha de hoy adentro, así que "esta semana"
    llega como la palabra `SEMANA` y se convierte acá, con el calendario local
    del negocio. Solo `RANGO` trae fechas propias, y para eso el mensaje del
    operador viaja con la fecha de hoy antepuesta (`claude.contexto_fecha`).

    Pura si se le pasa `hoy`: se testea sin BD ni reloj.

    Returns:
        (periodo_normalizado, desde, hasta)
    """
    hoy = hoy or hoy_local()
    periodo = str(data.get("periodo") or "").strip().upper()
    tipo = str(data.get("tipo") or "").strip().upper()

    if not periodo:
        # Sin período, cada consulta cae en lo que el operador quiso decir:
        # "movimientos" a secas es los de hoy; "cartera" a secas es toda.
        periodo = "HOY" if tipo in _CONSULTAS_DE_FLUJO else "TODO"

    if periodo == "HOY":
        return periodo, hoy, hoy
    if periodo == "AYER":
        ayer = hoy - timedelta(days=1)
        return periodo, ayer, ayer
    if periodo == "SEMANA":
        return periodo, hoy - timedelta(days=hoy.weekday()), hoy  # lunes a hoy
    if periodo == "MES":
        return periodo, hoy.replace(day=1), hoy
    if periodo == "RANGO":
        desde = _parse_date_val(data.get("desde"))
        hasta = _parse_date_val(data.get("hasta")) or hoy
        if desde is None:
            raise ValidationError(
                "¿Desde qué fecha? Decime el rango (ej: \"del 1 al 15 de agosto\")."
            )
        if desde > hasta:
            raise ValidationError(
                f"El rango está al revés: {_fmt_date(desde)} es posterior a {_fmt_date(hasta)}."
            )
        return periodo, desde, hasta

    # TODO y cualquier cosa que el modelo invente: sin límite hacia atrás.
    return "TODO", _ORIGEN, hoy


def _etiqueta_periodo(periodo: str, desde: date, hasta: date) -> str:
    """Cómo se nombra el período en el encabezado de la respuesta."""
    if periodo == "HOY":
        return f"hoy ({_fmt_date(desde)})"
    if periodo == "AYER":
        return f"ayer ({_fmt_date(desde)})"
    if periodo == "SEMANA":
        return f"esta semana ({_fmt_date(desde)} a {_fmt_date(hasta)})"
    if periodo == "MES":
        return f"este mes ({_fmt_date(desde)} a {_fmt_date(hasta)})"
    if periodo == "TODO":
        return "histórico"
    return f"del {_fmt_date(desde)} al {_fmt_date(hasta)}"


def _detalle(lineas: list[str], limite: int = _MAX_DETALLE) -> list[str]:
    """Recorta el detalle al tope y agrega el pie con lo que quedó afuera."""
    if len(lineas) <= limite:
        return lineas
    return [*lineas[:limite], f"… y {len(lineas) - limite} más (detalle completo en el panel)"]


def _monto(n: Decimal, moneda: Moneda) -> str:
    """Un importe con el símbolo de su moneda."""
    return f"{'U$D' if moneda == Moneda.USD else '$'}{_fmt_num(n)}"


def _totales_por_moneda(totales: dict[Moneda, Decimal]) -> str:
    """`{ARS: 100, USD: 5}` → `"$100,00 | U$D5,00"`. Vacío → `"$0,00"`."""
    partes = [_monto(t, m) for m, t in sorted(totales.items(), key=lambda kv: kv[0].value) if t]
    return " | ".join(partes) or "$0,00"


def _consulta(db: Session, data: dict[str, Any]) -> DispatchResult:
    """Entrada única de las consultas de lectura (intent `CONSULTA`).

    El `tipo` elige el handler y el `periodo` se resuelve una sola vez acá, así
    ninguna consulta se inventa su propio calendario."""
    tipo = str(data.get("tipo") or "").strip().upper()
    handler = _CONSULTAS.get(tipo)
    if handler is None:
        disponibles = ", ".join(sorted(_CONSULTAS)).lower()
        return False, (
            f"❓ No sé qué consultar. Puedo mostrarte: {disponibles}."
        )

    periodo, desde, hasta = _resolver_periodo(data)
    # Las consultas no limpian la sesión: no son transacciones, y el operador
    # suele preguntar algo y seguir la conversación sobre esa respuesta.
    return False, handler(db, desde, hasta, data, periodo)


# ── Cartera ──────────────────────────────────────────────────────────────────

def _neto_compra(cheque: Cheque) -> Decimal:
    """Lo que se pagó por el cheque: nominal menos el descuento de compra.

    Es la misma cuenta que hace el panel en `Cartera.tsx`; si alguna vez cambia,
    tiene que cambiar en los dos lados o el bot y la pantalla van a mostrar dos
    valores distintos para la misma cartera."""
    return (cheque.monto * (_CIEN_PCT - cheque.porcentaje_compra) / _CIEN_PCT).quantize(Decimal("0.01"))


def _totales_cartera(db: Session) -> tuple[list[Cheque], Decimal, Decimal]:
    """Cheques en stock con su nominal y su costo (nominal − descuento)."""
    cheques = svc_cheques.list_cheques(db, estado=ChequeEstado.EN_CARTERA)
    nominal = sum((c.monto for c in cheques), Decimal("0.00"))
    neto = sum((_neto_compra(c) for c in cheques), Decimal("0.00"))
    return cheques, nominal, neto


def _consulta_cartera(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    cheques, nominal, neto = _totales_cartera(db)

    if not cheques:
        return "📭 La cartera está vacía. No hay cheques en stock."

    diferencia = nominal - neto
    # Un decimal y con coma, como el resto de los números del mensaje: `_pct` usa
    # punto y sirve para los porcentajes enteros de un cheque, no para este.
    pct = (
        f" ({str((diferencia / nominal * _CIEN_PCT).quantize(Decimal('0.1'))).replace('.', ',')}%)"
        if nominal else ""
    )
    lines = [
        f"📊 *Cartera — {len(cheques)} cheque(s)*",
        f"Nominal: {_ars(nominal)}",
        f"Con descuento: {_ars(neto)}",
        f"Diferencia: {_ars(diferencia)}{pct}",
        "",
        "*Próximos a cobrar:*",
    ]

    detalle = [
        f"📄 Nº {c.nro_cheque} | {_ars(c.monto)} | Pago: "
        f"{_fmt_date(c.fecha_pago) if c.fecha_pago else 'sin fecha'} | "
        f"Compra: {_pct(c.porcentaje_compra)}%"
        for c in sorted(cheques, key=lambda x: x.fecha_pago or date.max)
    ]
    lines.extend(_detalle(detalle))

    return "\n".join(lines)


# ── Ventas de cartera ────────────────────────────────────────────────────────

def _consulta_ventas(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Qué cheques salieron de cartera en el período y qué dejaron.

    Se lee del libro de caja y no del estado del cheque: el estado dice cómo
    está hoy, pero no cuándo salió, y lo que el operador pregunta es qué pasó en
    estos días. Al revertir una venta su línea de caja se borra, así que lo que
    quedó acá es lo que de verdad ocurrió."""
    movs = list(
        db.scalars(
            select(MovimientoCaja)
            .where(
                MovimientoCaja.categoria.in_(
                    [CajaCategoria.VENTA_CHEQUE, CajaCategoria.COBRO_CHEQUE]
                ),
                MovimientoCaja.fecha >= desde,
                MovimientoCaja.fecha <= hasta,
            )
            .order_by(MovimientoCaja.fecha.desc(), MovimientoCaja.created_at.desc())
        )
    )

    etiqueta = _etiqueta_periodo(periodo, desde, hasta)
    if not movs:
        return f"📭 No hubo ventas ni cobros de cheques — {etiqueta}."

    ids = {m.referencia_id for m in movs if m.referencia_id is not None}
    cheques: dict[Any, Cheque] = (
        {c.id: c for c in db.scalars(select(Cheque).where(Cheque.id.in_(ids)))} if ids else {}
    )

    vendidos = [m for m in movs if m.categoria == CajaCategoria.VENTA_CHEQUE]
    cobrados = [m for m in movs if m.categoria == CajaCategoria.COBRO_CHEQUE]

    def _nominal(movimientos: list[MovimientoCaja]) -> Decimal:
        return sum(
            (cheques[m.referencia_id].monto for m in movimientos if m.referencia_id in cheques),
            Decimal("0.00"),
        )

    ganancia = sum(
        (cheques[m.referencia_id].ganancia for m in vendidos if m.referencia_id in cheques),
        Decimal("0.00"),
    )

    lines = [f"💸 *Ventas de cartera — {etiqueta}*", ""]
    if vendidos:
        cobrado = sum((m.monto for m in vendidos), Decimal("0.00"))
        lines.append(f"*Vendidos:* {len(vendidos)}")
        lines.append(f"  Nominal: {_ars(_nominal(vendidos))}")
        lines.append(f"  Cobrado: {_ars(cobrado)}")
        lines.append(f"  Ganancia: {_ars(ganancia)}")
    if cobrados:
        entrado = sum((m.monto for m in cobrados), Decimal("0.00"))
        lines.append(f"*Cobrados por ventanilla:* {len(cobrados)} — {_ars(entrado)}")
    lines.append("")

    detalle = []
    for m in movs:
        cheque = cheques.get(m.referencia_id)
        nro = cheque.nro_cheque if cheque else "?"
        if m.categoria == CajaCategoria.COBRO_CHEQUE:
            detalle.append(f"🏦 {_fmt_date(m.fecha)} | Nº {nro} | cobrado {_ars(m.monto)}")
            continue
        venta_pct = (
            f" al {_pct(cheque.porcentaje_venta)}%"
            if cheque is not None and cheque.porcentaje_venta is not None
            else ""
        )
        gan = f" | ganancia {_ars(cheque.ganancia)}" if cheque is not None else ""
        detalle.append(
            f"📄 {_fmt_date(m.fecha)} | Nº {nro}{venta_pct} → {_ars(m.monto)}{gan}"
        )
    lines.extend(_detalle(detalle))

    return "\n".join(lines)


def _consulta_cliente(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Resumen de lo que un cliente debe: préstamos, fiados y otras deudas (§2.b).

    Tiene que decir lo mismo que la sección Deudores del panel: si el bot omite
    una fuente, el operador consulta por WhatsApp y se lleva un saldo incompleto."""
    cliente_nombre = _req_str(data, "cliente_nombre")
    cliente = _buscar_cliente_o_error(db, cliente_nombre)

    lines = [f"👤 *{cliente.nombre}*"]
    hay_algo = False

    # Préstamos activos con cuotas pendientes
    prestamos: list[Prestamo] = list(
        db.scalars(
            select(Prestamo).where(
                Prestamo.cliente_id == cliente.id,
                Prestamo.estado == PrestamoEstado.ACTIVO,
                Prestamo.anulado_at.is_(None),
            )
        ).all()
    )
    if prestamos:
        hay_algo = True
        lines.append("")
        lines.append("💳 *Préstamos activos:*")
        for p in prestamos:
            cuotas_pendientes: list[Cuota] = list(
                db.scalars(
                    select(Cuota).where(
                        Cuota.prestamo_id == p.id,
                        Cuota.estado != CuotaEstado.COBRADA,
                    ).order_by(Cuota.numero_cuota.asc())
                ).all()
            )
            simbolo = "U$D" if p.moneda == Moneda.USD else "$"
            saldo = sum((c.monto for c in cuotas_pendientes), Decimal("0.00"))
            proxima = cuotas_pendientes[0] if cuotas_pendientes else None
            prox_txt = (
                f"próx. cuota #{proxima.numero_cuota}: {simbolo}{_fmt_num(proxima.monto)}"
                if proxima else "sin cuotas pendientes"
            )
            lines.append(
                f"  • Debe {simbolo}{_fmt_num(saldo)} de {simbolo}{_fmt_num(p.total_a_cobrar)} "
                f"en {p.cuotas} cuotas {_FRECUENCIA_PLURAL[p.frecuencia]} — {prox_txt} "
                f"({len(cuotas_pendientes)} de {p.cuotas} restante(s))"
            )

    # Fiados abiertos
    fiados: list[Fiado] = list(
        db.scalars(
            select(Fiado).where(
                Fiado.cliente_id == cliente.id,
                Fiado.estado == FiadoEstado.ABIERTO,
                Fiado.anulado_at.is_(None),
            )
        ).all()
    )
    if fiados:
        hay_algo = True
        lines.append("")
        lines.append("📋 *Fiados abiertos:*")
        for f in fiados:
            lines.append(f"  • Cheque Nº {f.cheque_nro} | Saldo: {_ars(f.saldo_pendiente)}")

    # Otras deudas (deudas libres, §2.b): no tienen cuotas ni cheque detrás, pero
    # son plata que el cliente debe igual. Sin este bloque el bot contestaba "no
    # tiene deudas activas" mientras el panel mostraba su saldo.
    otras: list[DeudaSimple] = list(
        db.scalars(
            select(DeudaSimple).where(
                DeudaSimple.cliente_id == cliente.id,
                DeudaSimple.estado == DeudaSimpleEstado.ABIERTA,
                DeudaSimple.anulado_at.is_(None),
            ).order_by(DeudaSimple.fecha.asc())
        ).all()
    )
    if otras:
        hay_algo = True
        lines.append("")
        lines.append("🧾 *Otras deudas:*")
        for d in otras:
            simbolo = "U$D" if d.moneda == Moneda.USD else "$"
            lines.append(
                f"  • {d.concepto} | Saldo: {simbolo}{_fmt_num(d.saldo_pendiente)}"
                f" ({_fmt_date(d.fecha)})"
            )
        # El total por moneda: es lo que el operador va a querer cobrar de una.
        for moneda in (Moneda.ARS, Moneda.USD):
            del_moneda = [d for d in otras if d.moneda == moneda]
            if len(del_moneda) > 1:
                simbolo = "U$D" if moneda == Moneda.USD else "$"
                total = sum((d.saldo_pendiente for d in del_moneda), Decimal("0.00"))
                lines.append(f"  Total {moneda.value}: {simbolo}{_fmt_num(total)}")

    if not hay_algo:
        lines.append("\nNo tiene deudas activas registradas.")

    return "\n".join(lines)


def _consulta_prestamos(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Lista todos los préstamos activos con lo que falta cobrar de cada uno."""
    prestamos: list[Prestamo] = list(
        db.scalars(
            select(Prestamo)
            .where(
                Prestamo.estado == PrestamoEstado.ACTIVO,
                Prestamo.anulado_at.is_(None),
            )
            .order_by(Prestamo.created_at.asc())
        ).all()
    )

    if not prestamos:
        return "📭 No tenés préstamos activos por cobrar."

    # Saldo pendiente por moneda = suma de cuotas pendientes.
    pendiente_por_moneda: dict[Moneda, Decimal] = {}
    lines: list[str] = [f"💳 *Préstamos activos — {len(prestamos)}*", ""]
    detalle: list[str] = []

    for p in prestamos:
        cuotas_pendientes: list[Cuota] = list(
            db.scalars(
                select(Cuota).where(
                    Cuota.prestamo_id == p.id,
                    Cuota.estado != CuotaEstado.COBRADA,
                ).order_by(Cuota.numero_cuota.asc())
            ).all()
        )
        saldo = sum((c.monto for c in cuotas_pendientes), Decimal("0.00"))
        pendiente_por_moneda[p.moneda] = pendiente_por_moneda.get(p.moneda, Decimal("0.00")) + saldo

        proxima = cuotas_pendientes[0] if cuotas_pendientes else None
        prox_txt = (
            f"próx. #{proxima.numero_cuota} ({_fmt_date(proxima.fecha_vencimiento)})"
            if proxima else "sin cuotas pendientes"
        )
        detalle.append(
            f"👤 {p.cliente.nombre} — falta {_monto(saldo, p.moneda)} "
            f"({len(cuotas_pendientes)} cuota(s), {prox_txt})"
        )

    lines.extend(_detalle(detalle))
    lines.append("")
    lines.append(f"*Total por cobrar:* {_totales_por_moneda(pendiente_por_moneda)}")

    return "\n".join(lines)


# ── Pasivos (lo que el negocio debe) ─────────────────────────────────────────

def _pasivos_pendientes(db: Session) -> list[Pasivo]:
    return list(
        db.scalars(
            select(Pasivo)
            .where(
                Pasivo.estado == PasivoEstado.PENDIENTE,
                Pasivo.anulado_at.is_(None),
            )
            .order_by(Pasivo.fecha_vencimiento.asc().nullslast())
        )
    )


def _totales_pasivos(db: Session) -> dict[Moneda, Decimal]:
    totales: dict[Moneda, Decimal] = {}
    for p in _pasivos_pendientes(db):
        totales[p.moneda] = totales.get(p.moneda, Decimal("0.00")) + p.saldo_pendiente
    return totales


def _consulta_pasivos(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Lo que el NEGOCIO debe, agrupado por acreedor (§5).

    Es el lado opuesto de DEUDORES y se pregunta casi igual ("las deudas"), así
    que el encabezado dice explícitamente de quién es la deuda: un operador que
    lee el número equivocado no tiene forma de darse cuenta."""
    pasivos = _pasivos_pendientes(db)
    if not pasivos:
        return "📭 No tenés deudas pendientes. El negocio no le debe nada a nadie."

    por_acreedor: dict[str, list[Pasivo]] = {}
    totales: dict[Moneda, Decimal] = {}
    for p in pasivos:
        por_acreedor.setdefault(p.acreedor, []).append(p)
        totales[p.moneda] = totales.get(p.moneda, Decimal("0.00")) + p.saldo_pendiente

    lines = [
        f"🧾 *Deudas del negocio — {len(pasivos)} pendiente(s)*",
        f"Total: {_totales_por_moneda(totales)}",
        "",
    ]

    def _saldo_ars(deudas: list[Pasivo]) -> Decimal:
        return sum(
            (d.saldo_pendiente for d in deudas if d.moneda == Moneda.ARS), Decimal("0.00")
        )

    detalle = []
    for acreedor, deudas in sorted(por_acreedor.items(), key=lambda kv: -_saldo_ars(kv[1])):
        del_acreedor: dict[Moneda, Decimal] = {}
        for d in deudas:
            del_acreedor[d.moneda] = del_acreedor.get(d.moneda, Decimal("0.00")) + d.saldo_pendiente
        cuanto = _totales_por_moneda(del_acreedor)
        if len(deudas) == 1:
            unica = deudas[0]
            vence = (
                f" · vence {_fmt_date(unica.fecha_vencimiento)}"
                if unica.fecha_vencimiento else ""
            )
            detalle.append(f"👤 {acreedor} — {cuanto} · {unica.concepto}{vence}")
        else:
            detalle.append(f"👤 {acreedor} — {cuanto} ({len(deudas)} deudas)")
    lines.extend(_detalle(detalle))

    return "\n".join(lines)


# ── Deudores (lo que los clientes deben) ─────────────────────────────────────

def _deuda_por_cliente(db: Session) -> list[tuple[str, dict[Moneda, Decimal]]]:
    """Saldo consolidado de cada cliente que debe algo, por moneda.

    Cruza las tres fuentes (§2.c) con la misma función que usa el cobro
    consolidado —`svc_deudores.armar_renglones`—, para que el total que ve el
    operador por chat sea exactamente el que se va a imputar cuando cobre. Las
    tres tablas se leen de una sola vez y se agrupan en memoria: preguntar
    "quién me debe" no puede disparar una consulta por cliente."""
    fiados = list(
        db.scalars(
            select(Fiado).where(
                Fiado.estado == FiadoEstado.ABIERTO,
                Fiado.anulado_at.is_(None),
            )
        )
    )
    deudas = list(
        db.scalars(
            select(DeudaSimple).where(
                DeudaSimple.estado == DeudaSimpleEstado.ABIERTA,
                DeudaSimple.anulado_at.is_(None),
            )
        )
    )
    prestamos = list(
        db.scalars(
            select(Prestamo)
            .options(selectinload(Prestamo.cuotas_detalle))
            .where(
                Prestamo.estado != PrestamoEstado.CANCELADO,
                Prestamo.anulado_at.is_(None),
            )
        )
    )

    ids = (
        {f.cliente_id for f in fiados}
        | {d.cliente_id for d in deudas}
        | {p.cliente_id for p in prestamos}
    )
    if not ids:
        return []
    nombres = {
        c.id: c.nombre for c in db.scalars(select(Cliente).where(Cliente.id.in_(ids)))
    }

    resultado: list[tuple[str, dict[Moneda, Decimal]]] = []
    for cliente_id in ids:
        del_cliente: dict[Moneda, Decimal] = {}
        for moneda in (Moneda.ARS, Moneda.USD):
            renglones = svc_deudores.armar_renglones(
                [f for f in fiados if f.cliente_id == cliente_id],
                [d for d in deudas if d.cliente_id == cliente_id],
                [p for p in prestamos if p.cliente_id == cliente_id],
                moneda,
            )
            total = sum((r.saldo for r in renglones), Decimal("0.00"))
            if total > 0:
                del_cliente[moneda] = total
        if del_cliente:
            resultado.append((nombres.get(cliente_id, "(cliente sin nombre)"), del_cliente))

    resultado.sort(key=lambda item: -item[1].get(Moneda.ARS, Decimal("0.00")))
    return resultado


def _consulta_deudores(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Lo que los CLIENTES deben, todos juntos (§2.c)."""
    por_cliente = _deuda_por_cliente(db)
    if not por_cliente:
        return "📭 Nadie te debe nada. No hay deudas de clientes abiertas."

    totales: dict[Moneda, Decimal] = {}
    for _, del_cliente in por_cliente:
        for moneda, monto in del_cliente.items():
            totales[moneda] = totales.get(moneda, Decimal("0.00")) + monto

    lines = [
        f"🫱 *Me deben — {len(por_cliente)} cliente(s)*",
        f"Total: {_totales_por_moneda(totales)}",
        "",
    ]
    lines.extend(
        _detalle([f"👤 {nombre} — {_totales_por_moneda(saldos)}" for nombre, saldos in por_cliente])
    )

    return "\n".join(lines)


# ── Movimientos y caja ───────────────────────────────────────────────────────

_EMOJI_FLUJO = {"INGRESO": "🟢", "EGRESO": "🔴", "NEUTRO": "⚪"}


def _consulta_movimientos(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Historial unificado del período: la misma fuente que la pantalla Movimientos."""
    items = svc_reportes.get_movimientos_unificados(db, desde, hasta)
    etiqueta = _etiqueta_periodo(periodo, desde, hasta)
    if not items:
        return f"📭 No hubo movimientos — {etiqueta}."

    ingresos: dict[Moneda, Decimal] = {}
    egresos: dict[Moneda, Decimal] = {}
    for it in items:
        moneda = Moneda(it.moneda)
        if it.flujo == "INGRESO":
            ingresos[moneda] = ingresos.get(moneda, Decimal("0.00")) + it.monto
        elif it.flujo == "EGRESO":
            egresos[moneda] = egresos.get(moneda, Decimal("0.00")) + it.monto

    lines = [
        f"📒 *Movimientos — {etiqueta}*",
        f"{len(items)} operación(es)",
        f"Ingresos: {_totales_por_moneda(ingresos)}",
        f"Egresos: {_totales_por_moneda(egresos)}",
        "",
    ]
    lines.extend(
        _detalle(
            [
                f"{_EMOJI_FLUJO.get(it.flujo, '•')} {_fmt_date(it.fecha)} | "
                f"{it.descripcion} | {_monto(it.monto, Moneda(it.moneda))}"
                for it in items
            ]
        )
    )

    return "\n".join(lines)


def _consulta_caja(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Caja del período: apertura, ingresos, egresos, neto y cierre por moneda.

    Es el mismo reporte que el cierre del panel (§7), así que los números tienen
    que coincidir mirando el celular o la pantalla."""
    reporte = svc_reportes.get_reporte_caja(db, desde, hasta)
    lines = [f"💰 *Caja — {_etiqueta_periodo(periodo, desde, hasta)}*"]

    for caja, moneda in ((reporte.ars, Moneda.ARS), (reporte.usd, Moneda.USD)):
        # La caja en dólares solo se muestra si tiene algo que decir: en un
        # negocio que operó todo el día en pesos, cuatro ceros son ruido.
        if moneda == Moneda.USD and not any(
            (caja.ingresos_total, caja.egresos_total, caja.saldo_apertura, caja.saldo_cierre)
        ):
            continue
        lines.extend(
            [
                "",
                f"*{moneda.value}*",
                f"Apertura: {_monto(caja.saldo_apertura, moneda)}",
                f"Ingresos: {_monto(caja.ingresos_total, moneda)}",
                f"Egresos: {_monto(caja.egresos_total, moneda)}",
                f"Neto: {_monto(caja.neto, moneda)}",
                f"Cierre: {_monto(caja.saldo_cierre, moneda)}",
            ]
        )

    if reporte.ganancia_divisas:
        lines.append("")
        lines.append(f"Ganancia por venta de dólares: {_ars(reporte.ganancia_divisas)}")

    pendientes = {
        Moneda.ARS: reporte.saldo_pasivos.pendiente_ars,
        Moneda.USD: reporte.saldo_pasivos.pendiente_usd,
    }
    if any(pendientes.values()):
        lines.append(f"Deudas pendientes: {_totales_por_moneda(pendientes)}")

    return "\n".join(lines)


# ── Gastos ───────────────────────────────────────────────────────────────────

def _consulta_gastos(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    gastos = list(
        db.scalars(
            select(GastoOperativo)
            .where(
                GastoOperativo.fecha_operacion >= desde,
                GastoOperativo.fecha_operacion <= hasta,
                GastoOperativo.anulado_at.is_(None),
            )
            .order_by(GastoOperativo.monto.desc())
        )
    )
    etiqueta = _etiqueta_periodo(periodo, desde, hasta)
    if not gastos:
        return f"📭 No hubo gastos — {etiqueta}."

    totales: dict[Moneda, Decimal] = {}
    for g in gastos:
        totales[g.moneda] = totales.get(g.moneda, Decimal("0.00")) + g.monto

    lines = [
        f"🧾 *Gastos — {etiqueta}*",
        f"{len(gastos)} gasto(s) — Total: {_totales_por_moneda(totales)}",
        "",
    ]
    lines.extend(
        _detalle(
            [
                f"• {g.concepto} — {_monto(g.monto, g.moneda)} ({_fmt_date(g.fecha_operacion)})"
                for g in gastos
            ]
        )
    )

    return "\n".join(lines)


# ── Divisas ──────────────────────────────────────────────────────────────────

def _consulta_divisas(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Stock de dólares (con su costo) y las operaciones del período.

    El stock sale de `usd_restante`, que es lo que el FIFO todavía no consumió:
    contar las compras enteras diría que hay dólares que ya se vendieron."""
    lotes = list(
        db.scalars(
            select(MovimientoEfectivo).where(
                MovimientoEfectivo.tipo == MovimientoEfectivoTipo.COMPRA,
                MovimientoEfectivo.usd_restante > 0,
                MovimientoEfectivo.anulado_at.is_(None),
            )
        )
    )
    stock = sum((lote.usd_restante for lote in lotes), Decimal("0.00"))
    costo = sum(
        (lote.usd_restante * lote.cotizacion_aplicada for lote in lotes), Decimal("0.00")
    )

    lines = ["💵 *Dólares*", f"Stock: U$D{_fmt_num(stock)}"]
    if stock > 0:
        promedio = (costo / stock).quantize(Decimal("0.01"))
        lines.append(f"Costo promedio: {_ars(promedio)} por dólar")
        lines.append(f"Valor de compra del stock: {_ars(costo)}")

    # `fecha_operacion` es un timestamp UTC: se consulta con la ventana ensanchada
    # y se filtra por fecha local, como hace el historial unificado, para no
    # traspapelar al día siguiente una operación cargada de noche.
    del_periodo = [
        m
        for m in db.scalars(
            select(MovimientoEfectivo)
            .where(
                func.date(MovimientoEfectivo.fecha_operacion) >= desde - timedelta(days=1),
                func.date(MovimientoEfectivo.fecha_operacion) <= hasta + timedelta(days=1),
                MovimientoEfectivo.anulado_at.is_(None),
                MovimientoEfectivo.es_ajuste.is_(False),
                MovimientoEfectivo.es_apertura.is_(False),
            )
            .order_by(MovimientoEfectivo.fecha_operacion.desc())
        )
        if desde <= fecha_local(m.fecha_operacion) <= hasta
    ]

    etiqueta = _etiqueta_periodo(periodo, desde, hasta)
    if not del_periodo:
        lines.append("")
        lines.append(f"Sin operaciones de divisas — {etiqueta}.")
        return "\n".join(lines)

    compras = [m for m in del_periodo if m.tipo == MovimientoEfectivoTipo.COMPRA]
    ventas = [m for m in del_periodo if m.tipo == MovimientoEfectivoTipo.VENTA]
    ganancia = sum((v.ganancia for v in ventas), Decimal("0.00"))

    lines.extend(["", f"*Operaciones — {etiqueta}*"])
    if compras:
        lines.append(
            f"Compras: {len(compras)} — U$D{_fmt_num(sum((c.monto for c in compras), Decimal('0.00')))}"
        )
    if ventas:
        lines.append(
            f"Ventas: {len(ventas)} — U$D{_fmt_num(sum((v.monto for v in ventas), Decimal('0.00')))}"
        )
        lines.append(f"Ganancia: {_ars(ganancia)}")
    lines.append("")
    lines.extend(
        _detalle(
            [
                f"{'🔴' if m.tipo == MovimientoEfectivoTipo.COMPRA else '🟢'} "
                f"{_fmt_date(fecha_local(m.fecha_operacion))} | "
                f"{'Compra' if m.tipo == MovimientoEfectivoTipo.COMPRA else 'Venta'} "
                f"U$D{_fmt_num(m.monto)} a {_ars(m.cotizacion_aplicada)}"
                for m in del_periodo
            ]
        )
    )

    return "\n".join(lines)


# ── Resumen general ──────────────────────────────────────────────────────────

def _consulta_resumen(
    db: Session, desde: date, hasta: date, data: dict[str, Any], periodo: str
) -> str:
    """Foto del negocio: qué hay, quién debe y cómo cerró el período."""
    cheques, nominal, neto = _totales_cartera(db)
    reporte = svc_reportes.get_reporte_caja(db, desde, hasta)

    deudores: dict[Moneda, Decimal] = {}
    for _, saldos in _deuda_por_cliente(db):
        for moneda, monto in saldos.items():
            deudores[moneda] = deudores.get(moneda, Decimal("0.00")) + monto

    lines = [
        f"📌 *Resumen — {_etiqueta_periodo(periodo, desde, hasta)}*",
        "",
        f"💰 Caja: {_ars(reporte.ars.saldo_cierre)}",
    ]
    if reporte.usd.saldo_cierre:
        lines.append(f"💵 Dólares: U$D{_fmt_num(reporte.usd.saldo_cierre)}")
    lines.extend(
        [
            "",
            f"📊 Cartera: {len(cheques)} cheque(s) — {_ars(nominal)} nominal, "
            f"{_ars(neto)} con descuento",
            f"🫱 Me deben: {_totales_por_moneda(deudores)}",
            f"🧾 Debo: {_totales_por_moneda(_totales_pasivos(db))}",
            "",
            f"Neto del período: {_ars(reporte.ars.neto)}",
        ]
    )
    if reporte.ganancia_divisas:
        lines.append(f"Ganancia por venta de dólares: {_ars(reporte.ganancia_divisas)}")

    return "\n".join(lines)


# Tipo de consulta → handler. Agregar una consulta nueva es una línea acá y un
# renglón en el prompt (§Bot): el ruteo no se toca.
_CONSULTAS = {
    "CARTERA":     _consulta_cartera,
    "VENTAS":      _consulta_ventas,
    "PASIVOS":     _consulta_pasivos,
    "DEUDORES":    _consulta_deudores,
    "CLIENTE":     _consulta_cliente,
    "PRESTAMOS":   _consulta_prestamos,
    "MOVIMIENTOS": _consulta_movimientos,
    "CAJA":        _consulta_caja,
    "GASTOS":      _consulta_gastos,
    "DIVISAS":     _consulta_divisas,
    "RESUMEN":     _consulta_resumen,
}


# ────────────────────────────────────────────────────────────────────────────
# Helpers de clientes
# ────────────────────────────────────────────────────────────────────────────

def _find_or_create_cliente(db: Session, nombre: str) -> Cliente:
    """Busca el cliente por nombre exacto. Si no existe, lo crea automáticamente."""
    nombre = nombre.strip().title()
    cliente = _buscar_cliente_exacto(db, nombre)
    if cliente:
        return cliente
    # Crear con los datos mínimos; el operador puede completarlo desde el dashboard
    return svc_clientes.create_cliente(db, ClienteCreate(nombre=nombre))


def _buscar_cliente_exacto(db: Session, nombre: str) -> Cliente | None:
    """Match exacto case-insensitive. Devuelve None si no existe.

    A diferencia de una búsqueda por substring, NO reutiliza un cliente cuyo
    nombre apenas *contenga* el texto: registrar para "Juan" no debe vincularse
    silenciosamente al cliente existente "Juan Pérez".
    """
    nombre = nombre.strip()
    return db.scalar(
        select(Cliente).where(func.lower(Cliente.nombre) == nombre.lower())
    )


def _buscar_cliente_o_error(db: Session, nombre: str, *, estricto: bool = False) -> Cliente:
    """Como _buscar_cliente_exacto pero lanza ValueError con mensaje diferenciado.

    Diferencia entre "no existe" y "nombre ambiguo" para dar feedback útil al operador.
    `estricto=True` desactiva el atajo de "match exacto único gana": ante varios
    candidatos por substring pide desambiguar siempre (se usa en operaciones de plata,
    donde cobrarle al deudor equivocado es costoso).
    """
    nombre = nombre.strip()
    resultados: list[Cliente] = list(
        db.scalars(
            select(Cliente).where(Cliente.nombre.ilike(f"%{nombre}%"))
        ).all()
    )
    return _elegir_cliente_match(resultados, nombre, estricto=estricto)


def _elegir_cliente_match(
    resultados: list[Cliente], nombre: str, *, estricto: bool = False
) -> Cliente:
    """Decide el cliente a partir de los candidatos por substring (ILIKE).

    Lógica pura (sin BD) para poder testearla de forma aislada.
    Lanza ValueError diferenciando "no existe" de "nombre ambiguo".

    En modo `estricto` (cobros), si hay más de un candidato se pide desambiguar
    siempre, aunque uno coincida EXACTO con el texto tecleado: el atajo de abajo
    es cómodo para consultas, pero para mover plata preferimos confirmar el deudor.
    """
    nombre = nombre.strip()
    if not resultados:
        raise ValueError(f"No encontré ningún cliente llamado '{nombre}'. ¿Cómo se llama exactamente?")
    if len(resultados) == 1:
        return resultados[0]
    # Si el texto tecleado coincide EXACTO (case-insensitive) con un único
    # candidato, gana: evita que un cliente cuyo nombre es substring de otro
    # (ej. "Rami" dentro de "Ramiro Velez") quede inalcanzable. Solo desambiguamos
    # cuando NO hay un único match exacto: un match exacto no debe ganar en silencio
    # frente a OTRO también exacto, pero sí frente a meros substrings más largos.
    # En modo estricto el atajo se saltea: ante varios candidatos, siempre preguntamos.
    objetivo = nombre.lower()
    exactos = [c for c in resultados if c.nombre.strip().lower() == objetivo]
    if not estricto and len(exactos) == 1:
        return exactos[0]
    # Varios candidatos sin match exacto único: preguntá cuál (ej: "Bono"
    # coincide con "Bono" y "Juan Bono"); resolver solo puede cobrarle al equivocado.
    nombres = ", ".join(c.nombre for c in resultados[:5])
    raise ValueError(
        f"Hay {len(resultados)} clientes que coinciden con '{nombre}': {nombres}. "
        "¿A cuál te referís? Decime el nombre completo."
    )


# ────────────────────────────────────────────────────────────────────────────
# Helpers de parsing de datos de Claude
# ────────────────────────────────────────────────────────────────────────────

def _req_str(data: dict, key: str) -> str:
    val = data.get(key)
    if not val:
        raise ValueError(f"Falta el campo '{key}' en la operación.")
    return str(val).strip()


def _req_decimal(data: dict, key: str) -> Decimal:
    val = data.get(key)
    if val is None:
        raise ValueError(f"Falta el campo numérico '{key}'.")
    try:
        return Decimal(str(val))
    except InvalidOperation:
        raise ValueError(f"El campo '{key}' no es un número válido: {val!r}")


def _opt_decimal(data: dict, key: str) -> Decimal | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except InvalidOperation:
        return None


def _req_int(data: dict, key: str) -> int:
    val = data.get(key)
    if val is None:
        raise ValueError(f"Falta el campo entero '{key}'.")
    try:
        return int(val)
    except (TypeError, ValueError):
        raise ValueError(f"El campo '{key}' no es un entero válido: {val!r}")


def _req_enum(data: dict, key: str, enum_cls: type) -> Any:
    val = data.get(key)
    if val is None:
        raise ValueError(f"Falta el campo '{key}'.")
    str_val = str(val)
    # Try exact value match first, then uppercase (Claude may return lowercase)
    try:
        return enum_cls(str_val)
    except ValueError:
        pass
    try:
        return enum_cls(str_val.upper())
    except ValueError:
        valid = [e.value for e in enum_cls]
        raise ValueError(f"Valor inválido para '{key}': {val!r}. Válidos: {valid}")


def _opt_date(data: dict, key: str) -> date | None:
    val = data.get(key)
    if not val:
        return None
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        return None


def _parse_decimal_val(val: Any) -> Decimal:
    try:
        return Decimal(str(val))
    except InvalidOperation:
        raise ValueError(f"Valor inválido (se esperaba un número): {val!r}")


_SI = {"true", "1", "si", "sí", "sip", "dale", "entro", "entró", "yes"}
_NO = {"false", "0", "no", "nop", "nada", "ninguno"}


def _parse_bool_val(val: Any) -> bool:
    """Sí/no del operador. Rechaza lo que no reconoce en vez de asumir `False`:
    el default silencioso acá borraría un ingreso de caja que sí existió."""
    if isinstance(val, bool):
        return val
    txt = str(val).strip().lower()
    if txt in _SI:
        return True
    if txt in _NO:
        return False
    raise ValueError(f"No entendí si va o no ({val!r}). Contestá 'sí' o 'no'.")


def _parse_date_val(val: Any) -> date | None:
    if val is None or str(val).strip().lower() in ("", "null", "none"):
        return None
    try:
        return date.fromisoformat(str(val))
    except ValueError:
        raise ValueError(f"Fecha inválida (usar YYYY-MM-DD): {val!r}")


def _resolver_cheque(db: Session, data: dict[str, Any]) -> Cheque:
    """Resuelve el cheque referido por el operador (número, posiblemente parcial,
    y banco opcional) a una fila concreta. Como el número ya no es único entre
    bancos, ante varios candidatos el servicio pide desambiguar por banco."""
    nro = _req_str(data, "nro_cheque")
    banco = (str(data["banco"]).strip() or None) if data.get("banco") else None
    return svc_cheques.resolve_cheque(db, nro, banco)


# ────────────────────────────────────────────────────────────────────────────
# Formateo de salida (estilo Argentina)
# ────────────────────────────────────────────────────────────────────────────

def _fmt_num(n: Decimal | float | int) -> str:
    """Formatea un número con puntos de miles y coma decimal (estilo AR)."""
    n = Decimal(str(n))
    # Redondear a 2 decimales
    n = n.quantize(Decimal("0.01"))
    # El signo se maneja aparte: int("-0") == 0 perdería el menos en (-1, 0).
    signo = "-" if n < 0 else ""
    parts = f"{abs(n):f}".split(".")
    int_part = f"{int(parts[0]):,}".replace(",", ".")
    return f"{signo}{int_part},{parts[1]}"


def _ars(n: Decimal) -> str:
    return f"${_fmt_num(n)}"


def _pct(n: Decimal) -> str:
    """Formatea un porcentaje sin ceros decimales innecesarios (ej. 3.0000 → '3', 3.5 → '3.5')."""
    return f"{float(n):g}"


def _fmt_date(d: date | None) -> str:
    if d is None:
        return "—"
    return d.strftime("%d/%m/%y")


# ────────────────────────────────────────────────────────────────────────────
# Advertencias de negocio (no bloquean — solo avisan al operador)
# ────────────────────────────────────────────────────────────────────────────

# Plazo legal de presentación de un cheque desde su fecha de pago (Argentina).
_PLAZO_PRESENTACION_DIAS = 30


def _advertencias_cheque(fecha_emision: date | None, fecha_pago: date | None) -> list[str]:
    """Avisos al registrar un cheque. Nunca bloquea: el operador decide."""
    hoy = hoy_local()
    avisos: list[str] = []

    if fecha_pago is not None and fecha_pago < hoy:
        limite = fecha_pago + timedelta(days=_PLAZO_PRESENTACION_DIAS)
        if hoy <= limite:
            avisos.append(
                f"⚠️ La fecha de pago ({_fmt_date(fecha_pago)}) ya pasó. "
                f"Todavía es presentable hasta el {_fmt_date(limite)} (plazo de 30 días)."
            )
        else:
            dias = (hoy - fecha_pago).days
            avisos.append(
                f"⚠️ Cheque *vencido*: la fecha de pago ({_fmt_date(fecha_pago)}) pasó hace "
                f"{dias} días y superó el plazo de presentación de 30 días."
            )

    if fecha_emision is not None and fecha_emision > hoy:
        avisos.append(f"⚠️ La fecha de emisión ({_fmt_date(fecha_emision)}) es futura.")

    return avisos
