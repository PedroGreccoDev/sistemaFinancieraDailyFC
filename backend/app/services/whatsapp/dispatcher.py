from __future__ import annotations

import difflib
import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import (
    Cheque,
    Cliente,
    Cuota,
    CuotaEstado,
    Fiado,
    FiadoEstado,
    GastoOperativo,
    MovimientoEfectivo,
    Pasivo,
    PasivoEstado,
    Prestamo,
    PrestamoEstado,
    ChequeEstado,
    FrecuenciaCuotas,
    Moneda,
    MovimientoEfectivoTipo,
)
from app.schemas.gastos_operativos import GastoOperativoCreate
from app.services import gastos_operativos as svc_gastos
from app.schemas.pasivos import PasivoCreate
from app.services import pasivos as svc_pasivos
from app.schemas.cheques import ChequeFiarRequest, ChequeCreate, ChequeManualTransition
from app.schemas.clientes import ClienteCreate
from app.schemas.fiados import FiadoCobrarConChequeRequest, FiadoCobrarEfectivoRequest
from app.schemas.movimientos import MovimientoEfectivoCreate
from app.schemas.prestamos import PrestamoCreate
from app.services import cheques as svc_cheques
from app.services import clientes as svc_clientes
from app.services import fiados as svc_fiados
from app.services import movimientos as svc_movimientos
from app.services import prestamos as svc_prestamos
from app.core.fechas import fecha_local, hora_local, hoy_local
from app.services.exceptions import ServiceError
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
        if intent == "REGISTRAR_DEUDA":
            return _registrar_deuda(db, data, msg_at)
        if intent == "MOVIMIENTO_EFECTIVO":
            return _movimiento_efectivo(db, data, msg_at)
        if intent == "REGISTRAR_GASTO":
            return _registrar_gasto(db, data, msg_at)
        if intent == "CONSULTA_CARTERA":
            return _consulta_cartera(db)
        if intent == "CONSULTA_CLIENTE":
            return _consulta_cliente(db, data)
        if intent == "CONSULTA_PRESTAMOS":
            return _consulta_prestamos(db)
        if intent == "EDITAR_OPERACION":
            return _editar_operacion(db, data)
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

def _registrar_cheque(
    db: Session,
    phone: str,
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

    payload = ChequeCreate(
        nro_cheque=nro,
        banco=banco,
        monto=monto,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        porcentaje_compra=pct_compra,
        cliente_origen_id=cliente_id,
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

    # Se registra igual (human in the loop); solo avisamos para que el operador revise.
    advertencias = _advertencias_cheque(fecha_emision, fecha_pago)
    if advertencias:
        lines.append("")
        lines.extend(advertencias)
    return True, "\n".join(lines)


def _vender_cheque(db: Session, phone: str, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
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

    cliente = _buscar_cliente_o_error(db, cliente_nombre)

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
    acreedor = _req_str(data, "acreedor")
    concepto = _req_str(data, "concepto")
    monto = _req_decimal(data, "monto")
    moneda = _req_enum(data, "moneda", Moneda) if data.get("moneda") else Moneda.ARS
    fecha_vencimiento = _opt_date(data, "fecha_vencimiento")

    payload = PasivoCreate(
        acreedor=acreedor,
        concepto=concepto,
        monto=monto,
        moneda=moneda,
        fecha_vencimiento=fecha_vencimiento,
    )
    pasivo = svc_pasivos.create_pasivo(db, payload, created_at=msg_at)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    lines = [
        f"📋 *Deuda registrada*",
        f"Acreedor: {pasivo.acreedor}",
        f"Concepto: {pasivo.concepto}",
        f"Monto: {simbolo}{_fmt_num(monto)}",
    ]
    if pasivo.fecha_vencimiento:
        lines.append(f"Vencimiento: {_fmt_date(pasivo.fecha_vencimiento)}")
    return True, "\n".join(lines)


def _movimiento_efectivo(db: Session, data: dict[str, Any], msg_at: datetime | None = None) -> DispatchResult:
    tipo = _req_enum(data, "tipo", MovimientoEfectivoTipo)
    moneda = _req_enum(data, "moneda", Moneda)
    monto = _req_decimal(data, "monto")
    cotizacion = _req_decimal(data, "cotizacion_aplicada")
    ganancia = _opt_decimal(data, "ganancia") or Decimal("0.00")
    observaciones: str | None = data.get("observaciones")

    cliente_id: uuid.UUID | None = None
    if cliente_nombre := data.get("cliente_nombre"):
        cliente = _find_or_create_cliente(db, str(cliente_nombre))
        cliente_id = cliente.id

    payload = MovimientoEfectivoCreate(
        cliente_id=cliente_id,
        tipo=tipo,
        moneda=moneda,
        monto=monto,
        cotizacion_aplicada=cotizacion,
        ganancia=ganancia,
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
    if mov.ganancia:
        lines.append(f"Ganancia: {_ars(mov.ganancia)}")
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
    cliente = _buscar_cliente_o_error(db, cliente_nombre)
    fiados: list[Fiado] = list(
        db.scalars(
            select(Fiado).where(
                Fiado.cliente_id == cliente.id,
                Fiado.estado == FiadoEstado.ABIERTO,
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
    if identificador.lower() == "ultimo":
        mov = db.scalars(
            select(MovimientoEfectivo).order_by(MovimientoEfectivo.created_at.desc()).limit(1)
        ).first()
    else:
        return False, "❓ Para movimientos indicá 'el último' o usá el panel web."

    if mov is None:
        return False, "❓ No encontré ningún movimiento registrado."

    campos_validos = {"monto", "cotizacion_aplicada", "ganancia", "tipo"}
    if campo not in campos_validos:
        return False, (
            f"⚠️ Campo inválido: '{campo}'. "
            f"Para movimientos podés corregir: {', '.join(sorted(campos_validos))}."
        )

    if campo == "tipo":
        try:
            nuevo_tipo = MovimientoEfectivoTipo(str(nuevo_valor).lower())
        except ValueError:
            try:
                nuevo_tipo = MovimientoEfectivoTipo(str(nuevo_valor).upper())
            except ValueError:
                return False, f"⚠️ Tipo inválido: '{nuevo_valor}'. Válidos: compra, venta."
        anterior = mov.tipo.value
        mov.tipo = nuevo_tipo
        db.commit()
        return True, f"✅ *Movimiento* — tipo corregido.\n{anterior} → {nuevo_tipo.value}"

    nuevo = _parse_decimal_val(nuevo_valor)
    anteriores = {
        "monto": _fmt_num(mov.monto),
        "cotizacion_aplicada": f"${_fmt_num(mov.cotizacion_aplicada)}",
        "ganancia": _ars(mov.ganancia),
    }
    setattr(mov, campo, nuevo)
    db.commit()
    return True, (
        f"✅ *Movimiento* — {campo} corregido.\n"
        f"{anteriores[campo]} → {_fmt_num(nuevo)}"
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
            select(GastoOperativo).order_by(GastoOperativo.created_at.desc()).limit(1)
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
            .where(GastoOperativo.fecha_operacion == hoy_local())
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
        db.commit()
        return True, f"✅ *Gasto '{gasto.concepto}'* — moneda corregida.\n{anterior} → {nueva_moneda.value}"

    nuevo = _parse_decimal_val(nuevo_valor)
    simbolo = "$" if gasto.moneda == Moneda.ARS else "U$D"
    anterior = f"{simbolo}{_fmt_num(gasto.monto)}"
    gasto.monto = nuevo
    db.commit()
    return True, f"✅ *Gasto '{gasto.concepto}'* — monto corregido.\n{anterior} → {simbolo}{_fmt_num(nuevo)}"


def _editar_pasivo(db: Session, identificador: str, campo: str, nuevo_valor: Any) -> DispatchResult:
    if identificador.lower() == "ultimo":
        pasivo = db.scalars(
            select(Pasivo)
            .where(Pasivo.estado == PasivoEstado.PENDIENTE)
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
                )
            ).all()
        )
        pasivo = resultados[0] if len(resultados) == 1 else None
        if pasivo is None and resultados:
            nombres = ", ".join(f"{p.acreedor} (${_fmt_num(p.monto)})" for p in resultados[:3])
            return False, f"❓ Encontré varios pasivos con '{identificador}': {nombres}. Sé más específico."

    if pasivo is None:
        return False, f"❓ No encontré ningún pasivo pendiente para '{identificador}'."

    campos_validos = {"acreedor", "concepto", "monto", "moneda", "fecha_vencimiento"}
    if campo not in campos_validos:
        return False, (
            f"⚠️ Campo inválido: '{campo}'. "
            f"Para pasivos podés corregir: {', '.join(sorted(campos_validos))}."
        )

    if campo in ("acreedor", "concepto"):
        anterior = getattr(pasivo, campo)
        setattr(pasivo, campo, str(nuevo_valor).strip())
        db.commit()
        return True, f"✅ *Pasivo* — {campo} corregido.\n'{anterior}' → '{nuevo_valor}'"

    if campo == "monto":
        nuevo = _parse_decimal_val(nuevo_valor)
        simbolo = "$" if pasivo.moneda == Moneda.ARS else "U$D"
        anterior = f"{simbolo}{_fmt_num(pasivo.monto)}"
        pasivo.monto = nuevo
        db.commit()
        return True, (
            f"✅ *Pasivo con {pasivo.acreedor}* — monto corregido.\n"
            f"{anterior} → {simbolo}{_fmt_num(nuevo)}"
        )

    if campo == "moneda":
        try:
            nueva_moneda = Moneda(str(nuevo_valor).upper())
        except ValueError:
            return False, f"⚠️ Moneda inválida: '{nuevo_valor}'. Válidas: ARS, USD."
        anterior = pasivo.moneda.value
        pasivo.moneda = nueva_moneda
        db.commit()
        return True, (
            f"✅ *Pasivo con {pasivo.acreedor}* — moneda corregida.\n"
            f"{anterior} → {nueva_moneda.value}"
        )

    # campo == "fecha_vencimiento"
    nuevo_d = _parse_date_val(nuevo_valor)
    anterior = _fmt_date(pasivo.fecha_vencimiento)
    pasivo.fecha_vencimiento = nuevo_d
    db.commit()
    return True, (
        f"✅ *Pasivo con {pasivo.acreedor}* — vencimiento corregido.\n"
        f"{anterior} → {_fmt_date(nuevo_d)}"
    )


def _consulta_cartera(db: Session) -> DispatchResult:
    cheques = svc_cheques.list_cheques(db, estado=ChequeEstado.EN_CARTERA)

    if not cheques:
        return False, "📭 La cartera está vacía. No hay cheques en stock."

    total = sum(c.monto for c in cheques)
    lines = [f"📊 *Cartera — {len(cheques)} cheque(s)*", f"Total: {_ars(total)}", ""]

    for c in sorted(cheques, key=lambda x: x.fecha_pago or date.max):
        pago = _fmt_date(c.fecha_pago) if c.fecha_pago else "sin fecha"
        lines.append(f"📄 Nº {c.nro_cheque} | {_ars(c.monto)} | Pago: {pago} | Compra: {_pct(c.porcentaje_compra)}%")

    return False, "\n".join(lines)  # No limpia sesión (es consulta, no transacción)


def _consulta_cliente(db: Session, data: dict[str, Any]) -> DispatchResult:
    """Muestra el resumen de deudas activas de un cliente: préstamos y fiados."""
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
            )
        ).all()
    )
    if fiados:
        hay_algo = True
        lines.append("")
        lines.append("📋 *Fiados abiertos:*")
        for f in fiados:
            lines.append(f"  • Cheque Nº {f.cheque_nro} | Saldo: {_ars(f.saldo_pendiente)}")

    if not hay_algo:
        lines.append("\nNo tiene deudas activas registradas.")

    return False, "\n".join(lines)


def _consulta_prestamos(db: Session) -> DispatchResult:
    """Lista todos los préstamos activos con lo que falta cobrar de cada uno."""
    prestamos: list[Prestamo] = list(
        db.scalars(
            select(Prestamo)
            .where(Prestamo.estado == PrestamoEstado.ACTIVO)
            .order_by(Prestamo.created_at.asc())
        ).all()
    )

    if not prestamos:
        return False, "📭 No tenés préstamos activos por cobrar."

    # Saldo pendiente por moneda = suma de cuotas pendientes.
    pendiente_por_moneda: dict[Moneda, Decimal] = {}
    lines: list[str] = [f"💳 *Préstamos activos — {len(prestamos)}*", ""]

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

        simbolo = "U$D" if p.moneda == Moneda.USD else "$"
        proxima = cuotas_pendientes[0] if cuotas_pendientes else None
        prox_txt = (
            f"próx. #{proxima.numero_cuota} ({_fmt_date(proxima.fecha_vencimiento)})"
            if proxima else "sin cuotas pendientes"
        )
        lines.append(
            f"👤 {p.cliente.nombre} — falta {simbolo}{_fmt_num(saldo)} "
            f"({len(cuotas_pendientes)} cuota(s), {prox_txt})"
        )

    lines.append("")
    totales = " | ".join(
        f"{'U$D' if m == Moneda.USD else '$'}{_fmt_num(t)}"
        for m, t in pendiente_por_moneda.items()
        if t > 0
    )
    lines.append(f"*Total por cobrar:* {totales or '$0,00'}")

    return False, "\n".join(lines)


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


def _buscar_cliente_o_error(db: Session, nombre: str) -> Cliente:
    """Como _buscar_cliente_exacto pero lanza ValueError con mensaje diferenciado.

    Diferencia entre "no existe" y "nombre ambiguo" para dar feedback útil al operador.
    """
    nombre = nombre.strip()
    resultados: list[Cliente] = list(
        db.scalars(
            select(Cliente).where(Cliente.nombre.ilike(f"%{nombre}%"))
        ).all()
    )
    if not resultados:
        raise ValueError(f"No encontré ningún cliente llamado '{nombre}'. ¿Cómo se llama exactamente?")
    if len(resultados) == 1:
        return resultados[0]
    # Varios candidatos: preguntá cuál, aunque uno coincida exacto. Un match exacto
    # NO debe ganar en silencio si hay otros que también coinciden (ej: "Bono"
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
