from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (
    Cliente,
    Cuota,
    CuotaEstado,
    Fiado,
    FiadoEstado,
    Prestamo,
    PrestamoEstado,
    ChequeEstado,
    FrecuenciaCuotas,
    Moneda,
    MovimientoEfectivoTipo,
)
from app.schemas.gastos_operativos import GastoOperativoCreate
from app.services import gastos_operativos as svc_gastos
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
from app.services.exceptions import ServiceError
from app.services.ia.claude import IntentResult

logger = logging.getLogger(__name__)

# ── Tipos de retorno ─────────────────────────────────────────────────────────
# (limpiar_sesion, texto_respuesta_whatsapp)
DispatchResult = tuple[bool, str]


# ────────────────────────────────────────────────────────────────────────────
# Entrypoint público
# ────────────────────────────────────────────────────────────────────────────

def dispatch(db: Session, phone: str, result: IntentResult) -> DispatchResult:
    """Ejecuta la operación correspondiente al intent y devuelve la respuesta.

    Returns:
        (limpiar_sesion, texto_para_whatsapp)
        limpiar_sesion=True solo cuando se impactó exitosamente la BD.
    """
    intent = result.intent
    data = result.data

    try:
        if intent == "REGISTRAR_CHEQUE":
            return _registrar_cheque(db, phone, data)
        if intent == "VENDER_CHEQUE":
            return _vender_cheque(db, phone, data)
        if intent == "FIAR_CHEQUE":
            return _fiar_cheque(db, phone, data)
        if intent == "COBRAR_CHEQUE":
            return _cobrar_cheque(db, phone, data)
        if intent == "RECHAZAR_CHEQUE":
            return _rechazar_cheque(db, phone, data)
        if intent == "NUEVO_PRESTAMO":
            return _nuevo_prestamo(db, data)
        if intent == "COBRAR_CUOTA":
            return _cobrar_cuota(db, data)
        if intent == "COBRAR_FIADO_EFECTIVO":
            return _cobrar_fiado_efectivo(db, phone, data)
        if intent == "COBRAR_FIADO_CON_CHEQUE":
            return _cobrar_fiado_con_cheque(db, phone, data)
        if intent == "MOVIMIENTO_EFECTIVO":
            return _movimiento_efectivo(db, data)
        if intent == "REGISTRAR_GASTO":
            return _registrar_gasto(db, data)
        if intent == "CONSULTA_CARTERA":
            return _consulta_cartera(db)
        # ACLARACION_REQUERIDA y DESCONOCIDO no tocan la BD
        return False, result.respuesta_usuario or "❓ No entendí. ¿Podés repetirlo?"

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

def _registrar_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
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
        monto=monto,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        porcentaje_compra=pct_compra,
        cliente_origen_id=cliente_id,
    )
    cheque = svc_cheques.create_cheque(db, payload)

    lines = [
        f"✅ *Cheque registrado en cartera*",
        f"Nº {cheque.nro_cheque}",
        f"Monto: {_ars(cheque.monto)}",
        f"Compra: {cheque.porcentaje_compra}%",
    ]
    if cheque.fecha_pago:
        lines.append(f"Pago: {_fmt_date(cheque.fecha_pago)}")

    # Se registra igual (human in the loop); solo avisamos para que el operador revise.
    advertencias = _advertencias_cheque(fecha_emision, fecha_pago)
    if advertencias:
        lines.append("")
        lines.extend(advertencias)
    return True, "\n".join(lines)


def _vender_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
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
    cheque = svc_cheques.transition_cheque(db, nro, payload)

    lines = [
        f"✅ *Cheque vendido*",
        f"Nº {cheque.nro_cheque}",
        f"Venta: {cheque.porcentaje_venta}% | Compra: {cheque.porcentaje_compra}%",
        f"Ganancia: {_ars(cheque.ganancia)}",
    ]
    # Venta por debajo del % de compra ⇒ pérdida. Se registra igual, solo avisamos.
    if cheque.ganancia is not None and cheque.ganancia < 0:
        lines.append("")
        lines.append(
            f"⚠️ *Venta a pérdida*: vendiste al {cheque.porcentaje_venta}%, "
            f"por debajo del {cheque.porcentaje_compra}% de compra."
        )
    return True, "\n".join(lines)


def _fiar_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
    cliente_nombre = _req_str(data, "cliente_nombre")
    pct_venta = _req_decimal(data, "porcentaje_venta")

    cliente = _find_or_create_cliente(db, cliente_nombre)

    request = ChequeFiarRequest(
        operador_id=phone,
        motivo=f"Fiado a {cliente.nombre}",
        cliente_destino_id=cliente.id,
        porcentaje_venta=pct_venta,
    )
    cheque, fiado = svc_cheques.fiar_cheque(db, nro, request)

    lines = [
        f"✅ *Cheque fiado*",
        f"Nº {cheque.nro_cheque} → {cliente.nombre}",
        f"Monto nominal: {_ars(cheque.monto)}",
        f"Descuento: {pct_venta}% | Saldo pendiente: {_ars(fiado.saldo_pendiente)}",
    ]
    return True, "\n".join(lines)


def _cobrar_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
    payload = ChequeManualTransition(
        target_state=ChequeEstado.COBRADO,
        operador_id=phone,
        motivo="Cobrado en ventanilla",
    )
    cheque = svc_cheques.transition_cheque(db, nro, payload)
    return True, f"✅ Cheque Nº {cheque.nro_cheque} marcado como *COBRADO*."


def _rechazar_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    nro = _req_str(data, "nro_cheque")
    payload = ChequeManualTransition(
        target_state=ChequeEstado.RECHAZADO,
        operador_id=phone,
        motivo="Rechazado — informado por operador",
    )
    cheque = svc_cheques.transition_cheque(db, nro, payload)
    return True, f"⛔ Cheque Nº {cheque.nro_cheque} marcado como *RECHAZADO*. Quedó en seguimiento."


def _nuevo_prestamo(db: Session, data: dict[str, Any]) -> DispatchResult:
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
        fecha_inicio=date.today(),
    )
    prestamo = svc_prestamos.create_prestamo(db, payload)

    simbolo = "U$D" if moneda == Moneda.USD else "$"
    lines = [
        f"✅ *Préstamo registrado*",
        f"Cliente: {cliente.nombre}",
        f"Crédito: {simbolo}{_fmt_num(credito)} | Total: {simbolo}{_fmt_num(total)}",
        f"{cuotas} cuotas {frecuencia.value}s",
        f"Ganancia: {simbolo}{_fmt_num(prestamo.ganancia)}",
    ]
    return True, "\n".join(lines)


def _cobrar_cuota(db: Session, data: dict[str, Any]) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    numero_cuota: int | None = data.get("numero_cuota")

    cliente = _buscar_cliente_exacto(db, cliente_nombre)
    if cliente is None:
        return False, f"❓ No encontré ningún cliente llamado '{cliente_nombre}'. ¿Cómo se llama exactamente?"

    # Buscar cuotas pendientes del cliente
    stmt = (
        select(Cuota)
        .join(Prestamo, Cuota.prestamo_id == Prestamo.id)
        .where(
            Prestamo.cliente_id == cliente.id,
            Prestamo.estado == PrestamoEstado.ACTIVO,
            Cuota.estado == CuotaEstado.PENDIENTE,
        )
        .order_by(Cuota.fecha_vencimiento.asc())
    )
    pendientes: list[Cuota] = list(db.scalars(stmt).all())

    if not pendientes:
        return False, f"ℹ️ {cliente.nombre} no tiene cuotas pendientes."

    if numero_cuota is not None:
        cuota = next((c for c in pendientes if c.numero_cuota == numero_cuota), None)
        if cuota is None:
            return False, (
                f"❓ No encontré la cuota #{numero_cuota} pendiente de {cliente.nombre}.\n"
                f"Cuotas pendientes: {', '.join(f'#{c.numero_cuota}' for c in pendientes)}"
            )
    else:
        # Cobrar la primera (más próxima a vencer)
        cuota = pendientes[0]

    cobrada = svc_prestamos.cobrar_cuota(db, cuota.prestamo_id, cuota.id, fecha_cobro=date.today())

    # Si todas las cuotas están cobradas, informarlo
    restantes = len(pendientes) - 1
    extra = f"\n✨ Préstamo *cancelado* — todas las cuotas cobradas." if restantes == 0 else f"\nQuedan {restantes} cuota(s) pendiente(s)."

    return True, (
        f"✅ Cuota #{cobrada.numero_cuota} de {cliente.nombre} cobrada.\n"
        f"Monto: {_ars(cobrada.monto)}{extra}"
    )


def _movimiento_efectivo(db: Session, data: dict[str, Any]) -> DispatchResult:
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


def _registrar_gasto(db: Session, data: dict[str, Any]) -> DispatchResult:
    concepto = _req_str(data, "concepto")
    monto = _req_decimal(data, "monto")
    moneda = _req_enum(data, "moneda", Moneda) if data.get("moneda") else Moneda.ARS

    payload = GastoOperativoCreate(
        concepto=concepto,
        monto=monto,
        moneda=moneda,
    )
    gasto = svc_gastos.create_gasto(db, payload)

    simbolo = "U$D" if gasto.moneda == Moneda.USD else "$"
    return True, (
        f"💸 *Gasto registrado*\n"
        f"Concepto: {gasto.concepto}\n"
        f"Monto: {simbolo}{_fmt_num(gasto.monto)}"
    )


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
            f"Cobrado: {_ars(monto_cobrado)} | Saldo: {_ars(fiado_actualizado.saldo_pendiente)}\n"
            f"🎉 Deuda saldada completamente."
        )
    return True, (
        f"✅ *Pago parcial registrado* — {cliente_nombre}\n"
        f"Cobrado: {_ars(monto_cobrado)}\n"
        f"Saldo restante: {_ars(fiado_actualizado.saldo_pendiente)}"
    )


def _cobrar_fiado_con_cheque(db: Session, phone: str, data: dict[str, Any]) -> DispatchResult:
    cliente_nombre = _req_str(data, "cliente_nombre")
    nro_cheque_pago = _req_str(data, "nro_cheque_pago")
    monto_cheque = _req_decimal(data, "monto_cheque")
    pct_compra = _req_decimal(data, "porcentaje_compra_cheque")
    fecha_emision = _opt_date(data, "fecha_emision")
    fecha_pago = _opt_date(data, "fecha_pago")

    fiado = _buscar_fiado_abierto(db, cliente_nombre)
    if fiado is None:
        return False, f"❓ No encontré un fiado abierto para '{cliente_nombre}'."

    payload = FiadoCobrarConChequeRequest(
        nro_cheque_pago=nro_cheque_pago,
        monto_cheque=monto_cheque,
        porcentaje_compra_cheque=pct_compra,
        fecha_emision=fecha_emision,
        fecha_pago=fecha_pago,
        operador_id=phone,
    )
    resultado = svc_fiados.cobrar_con_cheque(db, fiado.id, payload)

    fiado_act = resultado.fiado
    diferencia = resultado.diferencia
    cheque_nuevo = resultado.cheque_ingresado

    lines = [
        f"✅ *Cheque recibido como pago de fiado* — {cliente_nombre}",
        f"Cheque Nº {cheque_nuevo.nro_cheque} | Nominal: {_ars(monto_cheque)} | Compra: {pct_compra}%",
        f"Valor neto: {_ars(monto_cheque * (100 - pct_compra) / 100)}",
    ]

    if fiado_act.estado == FiadoEstado.CANCELADO:
        lines.append(f"🎉 Fiado *cancelado* — deuda saldada.")
        if diferencia > 0:
            lines.append(f"⚠️ Le debés al cliente: {_ars(diferencia)}")
    else:
        lines.append(f"Saldo restante del fiado: {_ars(fiado_act.saldo_pendiente)}")

    return True, "\n".join(lines)


def _buscar_fiado_abierto(db: Session, cliente_nombre: str) -> Fiado | None:
    """Devuelve el fiado ABIERTO del cliente, o None si no hay exactamente uno."""
    cliente = _buscar_cliente_exacto(db, cliente_nombre)
    if cliente is None:
        return None
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
    return None


def _consulta_cartera(db: Session) -> DispatchResult:
    cheques = svc_cheques.list_cheques(db, estado=ChequeEstado.EN_CARTERA)

    if not cheques:
        return False, "📭 La cartera está vacía. No hay cheques en stock."

    total = sum(c.monto for c in cheques)
    lines = [f"📊 *Cartera — {len(cheques)} cheque(s)*", f"Total: {_ars(total)}", ""]

    for c in sorted(cheques, key=lambda x: x.fecha_pago or date.max):
        pago = _fmt_date(c.fecha_pago) if c.fecha_pago else "sin fecha"
        lines.append(f"📄 Nº {c.nro_cheque} | {_ars(c.monto)} | Pago: {pago} | Compra: {c.porcentaje_compra}%")

    return False, "\n".join(lines)  # No limpia sesión (es consulta, no transacción)


# ────────────────────────────────────────────────────────────────────────────
# Helpers de clientes
# ────────────────────────────────────────────────────────────────────────────

def _find_or_create_cliente(db: Session, nombre: str) -> Cliente:
    """Busca el cliente por nombre. Si no existe, lo crea automáticamente."""
    nombre = nombre.strip().title()
    cliente = _buscar_cliente_exacto(db, nombre)
    if cliente:
        return cliente
    # Crear con los datos mínimos; el operador puede completarlo desde el dashboard
    return svc_clientes.create_cliente(db, ClienteCreate(nombre=nombre))


def _buscar_cliente_exacto(db: Session, nombre: str) -> Cliente | None:
    """Búsqueda case-insensitive. Si hay múltiples coincidencias, devuelve None."""
    nombre = nombre.strip()
    resultados: list[Cliente] = list(
        db.scalars(
            select(Cliente).where(Cliente.nombre.ilike(f"%{nombre}%"))
        ).all()
    )
    if len(resultados) == 1:
        return resultados[0]
    # Exacto primero
    exacto = next((c for c in resultados if c.nombre.lower() == nombre.lower()), None)
    return exacto


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


# ────────────────────────────────────────────────────────────────────────────
# Formateo de salida (estilo Argentina)
# ────────────────────────────────────────────────────────────────────────────

def _fmt_num(n: Decimal | float | int) -> str:
    """Formatea un número con puntos de miles y coma decimal (estilo AR)."""
    n = Decimal(str(n))
    # Redondear a 2 decimales
    n = n.quantize(Decimal("0.01"))
    # Separar parte entera y decimal
    parts = f"{n:f}".split(".")
    int_part = f"{int(parts[0]):,}".replace(",", ".")
    return f"{int_part},{parts[1]}"


def _ars(n: Decimal) -> str:
    return f"${_fmt_num(n)}"


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
    hoy = date.today()
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
