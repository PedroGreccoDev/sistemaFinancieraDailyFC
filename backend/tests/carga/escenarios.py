"""El catálogo de operaciones que la sesión dispara al azar.

Cada escenario es una operación del negocio como la haría el operador: cargar un
cheque, venderlo, cobrarle a un cliente, pagar una deuda, depositar plata en el
banco. La sesión los elige con un generador de semilla fija y los encadena.

**Por el bot se entra por `dispatcher.dispatch` con el `IntentResult` ya
armado**, sin pasar por el modelo. No es una simulación pobre: `dispatch` es
exactamente lo que corre en producción una vez que la IA tradujo el mensaje, y
saltearla hace la sesión reproducible, gratis y mil veces más rápida. Lo que el
modelo aporta —entender la frase— se prueba aparte, con las corridas de IA real.

**Los datos son variados a propósito**: montos con centavos, porcentajes con
decimales, nombres con acentos, fechas pasadas y futuras. Un catálogo con
valores redondos y prolijos encuentra mucho menos.

Los escenarios **eligen entidades que ya existen** en vez de crear todo de cero:
así la base se va enredando corrida a corrida —un cheque comprado, vendido,
revertido y vuelto a vender— que es donde aparecen los bugs de verdad.

Ver §Sesión de carga.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.db.models import (
    Cheque,
    ChequeEstado,
    Cliente,
    DeudaSimple,
    DeudaSimpleEstado,
    Fiado,
    FiadoEstado,
    Pasivo,
    PasivoEstado,
    Prestamo,
    PrestamoEstado,
)
from app.services.ia.contrato import IntentResult
from app.services.whatsapp import dispatcher as wa_dispatcher

NOMBRES = (
    "Juan Pérez", "Kiosco El Ñandú", "María González", "Olivero", "Cuello",
    "Pedrón", "Martín Ávila", "Distribuidora San José", "Bono", "Rodríguez e Hijos",
)
ACREEDORES = ("Pedro Mayorista", "Cuello", "Martín Ávila", "Financiera Sur")
BANCOS = ("Galicia", "Nación", "Santander", "Macro", None)
CONCEPTOS_GASTO = ("nafta", "almuerzo", "estacionamiento", "insumos", "peaje", "café")


@dataclass
class Contexto:
    """Lo que un escenario necesita para operar."""

    db:      Session
    client:  Any            # TestClient del panel (None si la corrida es solo bot)
    headers: dict[str, str]
    rng:     random.Random
    phone:   str
    sesion:  str


@dataclass
class Resultado:
    """Qué pasó con una corrida.

    `rechazo` no es un error: es el sistema diciendo que no ("el cheque ya está
    vendido", "no hay stock"). La sesión los cuenta aparte porque son la
    operación normal del negocio — y porque una sesión donde **todo** se rechaza
    tampoco está probando nada, así que el número importa.
    """

    ok:      bool
    detalle: str = ""
    rechazo: str | None = None


# ══════════════════════════════════════════════════════════════════════
#  Generadores de datos
# ══════════════════════════════════════════════════════════════════════

def _monto(rng: random.Random, minimo: int = 1_000, maximo: int = 3_000_000) -> Decimal:
    """Un importe con centavos: el redondeo es donde se pierden las diferencias."""
    entero = rng.randint(minimo, maximo)
    centavos = rng.choice([0, 1, 33, 50, 99])
    return Decimal(f"{entero}.{centavos:02d}")


def _porcentaje(rng: random.Random) -> Decimal:
    return Decimal(str(rng.choice([1, 2, 2.5, 3, 4, 5.75, 8, 10, 12.5])))


def _cotizacion(rng: random.Random) -> Decimal:
    return Decimal(str(rng.randint(900, 1600)))


def _fecha(rng: random.Random, desde: int = -60, hasta: int = 60) -> date:
    return date.today() + timedelta(days=rng.randint(desde, hasta))


def _nro_cheque(rng: random.Random) -> str:
    return str(rng.randint(10_000_000, 99_999_999))


def _nombre(rng: random.Random) -> str:
    return rng.choice(NOMBRES)


# ══════════════════════════════════════════════════════════════════════
#  Elegir algo que ya existe
# ══════════════════════════════════════════════════════════════════════

def _uno_al_azar(db: Session, stmt, rng: random.Random):
    """Una fila al azar de las primeras que devuelva la consulta, o None.

    El `LIMIT 40` es para no traerse miles de filas por corrida: alcanza para
    que la elección sea variada y cuesta lo mismo siempre.
    """
    filas = list(db.scalars(stmt.limit(40)))
    return rng.choice(filas) if filas else None


def _cheque_en_cartera(ctx: Contexto) -> Cheque | None:
    return _uno_al_azar(
        ctx.db,
        sa.select(Cheque)
        .where(Cheque.estado == ChequeEstado.EN_CARTERA, Cheque.anulado_at.is_(None))
        .order_by(Cheque.created_at.desc()),
        ctx.rng,
    )


def _cliente_con_deuda(ctx: Contexto) -> str | None:
    """Un cliente que debe por alguna de las tres vías (§2.c)."""
    for modelo, estado_vivo in (
        (Fiado, Fiado.estado == FiadoEstado.ABIERTO),
        (DeudaSimple, DeudaSimple.estado == DeudaSimpleEstado.ABIERTA),
        (Prestamo, Prestamo.estado == PrestamoEstado.ACTIVO),
    ):
        fila = _uno_al_azar(
            ctx.db,
            sa.select(Cliente)
            .join(modelo, modelo.cliente_id == Cliente.id)
            .where(estado_vivo, modelo.anulado_at.is_(None)),
            ctx.rng,
        )
        if fila is not None:
            return fila.nombre
    return None


def _acreedor_con_deuda(ctx: Contexto) -> str | None:
    fila = _uno_al_azar(
        ctx.db,
        sa.select(Pasivo).where(
            Pasivo.estado == PasivoEstado.PENDIENTE, Pasivo.anulado_at.is_(None)
        ),
        ctx.rng,
    )
    return fila.acreedor if fila is not None else None


# ══════════════════════════════════════════════════════════════════════
#  Ejecutar por el bot
# ══════════════════════════════════════════════════════════════════════

def _bot(ctx: Contexto, intent: str, data: dict[str, Any]) -> Resultado:
    """Manda la operación por el mismo camino que un mensaje de WhatsApp.

    `dispatch` atrapa `ServiceError` y devuelve el texto con ⚠️: eso es el
    negocio diciendo que no y se cuenta como rechazo. Lo que sí importa es la
    otra rama, la del `except Exception`, que loguea y contesta "error interno":
    esa ya quedó anotada como bug por la captura de logs antes de volver acá.
    """
    try:
        _, respuesta = wa_dispatcher.dispatch(
            ctx.db, ctx.phone, IntentResult(intent=intent, data=data)
        )
    except wa_dispatcher.ConfirmacionRequerida as exc:
        ctx.db.rollback()
        return Resultado(ok=True, rechazo=f"pidió confirmación: {exc}"[:200])
    except Exception as exc:  # noqa: BLE001 — la sesión no se corta por una corrida
        ctx.db.rollback()
        return Resultado(ok=False, detalle=f"{type(exc).__name__}: {exc}"[:500])

    if respuesta.startswith("⚠️"):
        return Resultado(ok=True, rechazo=respuesta.replace("\n", " ")[:200])
    return Resultado(ok=True, detalle=respuesta.splitlines()[0][:200])


def _panel(ctx: Contexto, metodo: str, ruta: str, payload: dict | None = None) -> Resultado:
    """Golpea el panel por HTTP, como lo haría el navegador del operador.

    Un 4xx es el sistema validando y se cuenta como rechazo. **Un 500 ya es un
    bug** —lo anotó el handler global antes de contestar— y acá solo se cuenta.
    """
    if ctx.client is None:
        return Resultado(ok=True, rechazo="sin panel en esta corrida")

    resp = ctx.client.request(
        metodo, f"/api/v1{ruta}", json=payload, headers=ctx.headers
    )
    if resp.status_code >= 500:
        return Resultado(ok=False, detalle=f"HTTP {resp.status_code} en {metodo} {ruta}")
    if resp.status_code >= 400:
        return Resultado(ok=True, rechazo=f"HTTP {resp.status_code}: {resp.text[:150]}")
    return Resultado(ok=True, detalle=f"HTTP {resp.status_code} {metodo} {ruta}")


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — cheques
# ══════════════════════════════════════════════════════════════════════

def registrar_cheque(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    monto = _monto(rng, 50_000, 5_000_000)
    data: dict[str, Any] = {
        "cheques": [
            {
                "nro_cheque": _nro_cheque(rng),
                "banco": rng.choice(BANCOS),
                "monto": float(monto),
                "porcentaje_compra": float(_porcentaje(rng)),
                "fecha_emision": _fecha(rng, -90, 0).isoformat(),
                "fecha_pago": _fecha(rng, 0, 120).isoformat(),
                "cliente_nombre": _nombre(rng),
                "medio_pago": rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
            }
        ]
    }
    # Una de cada cinco compras queda a deber: es el caso que arma un pasivo solo
    # y el que más veces se rompió históricamente (§Comprar sin abonar).
    if rng.random() < 0.2:
        data["cheques"][0]["monto_abonado"] = float(_monto(rng, 0, int(monto / 2)))
    return _bot(ctx, "REGISTRAR_CHEQUE", data)


def vender_cheque(ctx: Contexto) -> Resultado:
    cheque = _cheque_en_cartera(ctx)
    if cheque is None:
        return Resultado(ok=True, rechazo="no hay cheques en cartera")
    return _bot(
        ctx,
        "VENDER_CHEQUE",
        {
            "ventas": [
                {
                    "nro_cheque": cheque.nro_cheque,
                    "banco": cheque.banco,
                    "porcentaje_venta": float(_porcentaje(ctx.rng)),
                    "cliente_nombre": _nombre(ctx.rng),
                    "medio_pago": ctx.rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
                }
            ]
        },
    )


def fiar_cheque(ctx: Contexto) -> Resultado:
    cheque = _cheque_en_cartera(ctx)
    if cheque is None:
        return Resultado(ok=True, rechazo="no hay cheques en cartera")
    return _bot(
        ctx,
        "FIAR_CHEQUE",
        {
            "nro_cheque": cheque.nro_cheque,
            "banco": cheque.banco,
            "porcentaje_venta": float(_porcentaje(ctx.rng)),
            "cliente_nombre": _nombre(ctx.rng),
        },
    )


def cobrar_cheque(ctx: Contexto) -> Resultado:
    cheque = _cheque_en_cartera(ctx)
    if cheque is None:
        return Resultado(ok=True, rechazo="no hay cheques en cartera")
    return _bot(
        ctx,
        "COBRAR_CHEQUE",
        {"nro_cheque": cheque.nro_cheque, "banco": cheque.banco},
    )


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — deudas y cobros
# ══════════════════════════════════════════════════════════════════════

def registrar_deuda_cliente(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    return _bot(
        ctx,
        "REGISTRAR_DEUDA_CLIENTE",
        {
            "cliente_nombre": _nombre(rng),
            "concepto": rng.choice(["adelanto", "mercadería", "préstamo suelto"]),
            "monto": float(_monto(rng, 5_000, 800_000)),
            "moneda": rng.choice(["ARS", "ARS", "USD"]),
            "fecha": _fecha(rng, -30, 0).isoformat(),
        },
    )


def registrar_deuda_negocio(ctx: Contexto) -> Resultado:
    """La deuda del negocio, que a veces trae plata a la caja (§5)."""
    rng = ctx.rng
    entro_plata = rng.random() < 0.3
    moneda = rng.choice(["ARS", "ARS", "USD"])
    data: dict[str, Any] = {
        "acreedor": rng.choice(ACREEDORES),
        "concepto": rng.choice(["compra de dólares", "lote de cheques", "préstamo"]),
        "monto": float(_monto(rng, 10_000, 2_000_000)),
        "moneda": moneda,
        "ingreso_caja": entro_plata,
    }
    if entro_plata and moneda == "USD":
        # Sin la cotización esos dólares entran a la caja y no se pueden vender.
        data["cotizacion_ingreso_usd"] = float(_cotizacion(rng))
    return _bot(ctx, "REGISTRAR_DEUDA", data)


def cobrar_deuda_cliente(ctx: Contexto) -> Resultado:
    nombre = _cliente_con_deuda(ctx)
    if nombre is None:
        return Resultado(ok=True, rechazo="nadie debe nada todavía")

    rng = ctx.rng
    moneda_pago = rng.choice(["ARS", "ARS", "ARS", "USD"])
    data: dict[str, Any] = {
        "cliente_nombre": nombre,
        "monto_cobrado": float(_monto(rng, 1_000, 500_000)),
        "moneda_pago": moneda_pago,
        "moneda_deuda": "ARS",
        "medio_pago": rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
    }
    if moneda_pago == "USD":
        # Cruza monedas: la cotización imputa cuánto baja la deuda en pesos.
        data["cotizacion"] = float(_cotizacion(rng))
    return _bot(ctx, "COBRAR_DEUDA_CLIENTE", data)


def pagar_pasivo(ctx: Contexto) -> Resultado:
    acreedor = _acreedor_con_deuda(ctx)
    if acreedor is None:
        return Resultado(ok=True, rechazo="el negocio no le debe a nadie")
    return _bot(
        ctx,
        "PAGAR_PASIVO",
        {
            "acreedor": acreedor,
            "monto": float(_monto(ctx.rng, 1_000, 400_000)),
            "moneda_pago": "ARS",
            "moneda_deuda": "ARS",
            "medio_pago": ctx.rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
        },
    )


def compensar_deuda(ctx: Contexto) -> Resultado:
    """El cliente le paga a un acreedor del negocio: no se mueve la caja."""
    cliente = _cliente_con_deuda(ctx)
    acreedor = _acreedor_con_deuda(ctx)
    if cliente is None or acreedor is None:
        return Resultado(ok=True, rechazo="faltan las dos puntas de la compensación")
    return _bot(
        ctx,
        "COMPENSAR_DEUDA",
        {
            "cliente_nombre": cliente,
            "acreedor_nombre": acreedor,
            "monto": float(_monto(ctx.rng, 1_000, 300_000)),
            "moneda": "ARS",
            "moneda_deuda": "ARS",
            "moneda_pasivo": "ARS",
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — préstamos
# ══════════════════════════════════════════════════════════════════════

def nuevo_prestamo(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    credito = _monto(rng, 50_000, 1_500_000)
    return _bot(
        ctx,
        "NUEVO_PRESTAMO",
        {
            "cliente_nombre": _nombre(rng),
            "credito": float(credito),
            "moneda": rng.choice(["ARS", "ARS", "USD"]),
            "cuotas": rng.choice([2, 3, 4, 6, 12]),
            "frecuencia": rng.choice(["diaria", "semanal", "quincenal", "mensual"]),
            # El total siempre por encima del crédito: es la ganancia del préstamo.
            "total_a_cobrar": float(credito * Decimal(str(rng.choice([1.15, 1.3, 1.5, 2.0])))),
        },
    )


def cobrar_cuota(ctx: Contexto) -> Resultado:
    fila = _uno_al_azar(
        ctx.db,
        sa.select(Cliente)
        .join(Prestamo, Prestamo.cliente_id == Cliente.id)
        .where(Prestamo.estado == PrestamoEstado.ACTIVO, Prestamo.anulado_at.is_(None)),
        ctx.rng,
    )
    if fila is None:
        return Resultado(ok=True, rechazo="no hay préstamos activos")
    return _bot(
        ctx,
        "COBRAR_CUOTA",
        {
            "cliente_nombre": fila.nombre,
            "numero_cuota": None,
            "cantidad_cuotas": ctx.rng.choice([1, 1, 1, 2]),
            "medio_pago": ctx.rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — caja y divisas
# ══════════════════════════════════════════════════════════════════════

def operacion_divisas(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    tipo = rng.choice(["compra", "compra", "venta"])
    data: dict[str, Any] = {
        "tipo": tipo,
        "moneda": "USD",
        "monto": float(Decimal(str(rng.randint(50, 5_000)))),
        "cotizacion_aplicada": float(_cotizacion(rng)),
        "cliente_nombre": _nombre(rng),
        # Los pesos pueden ir por cualquiera de las dos cajas...
        "medio_pago": rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
        # ...los dólares no: **el negocio no tiene cuenta en dólares** (dicho por
        # el dueño, 2026-08-25). Los billetes se dan y se reciben en mano.
        "medio_usd": "EFECTIVO",
    }
    if tipo == "compra" and rng.random() < 0.2:
        data["monto_abonado"] = 0
    return _bot(ctx, "MOVIMIENTO_EFECTIVO", data)


def traspaso_caja(ctx: Contexto) -> Resultado:
    """Depositar o extraer: la plata cambia de caja, no entra ni sale."""
    rng = ctx.rng
    deposita = rng.random() < 0.5
    return _bot(
        ctx,
        "TRASPASO_CAJA",
        {
            "monto": float(_monto(rng, 10_000, 1_000_000)),
            "moneda": "ARS",
            "origen": "EFECTIVO" if deposita else "TRANSFERENCIA",
            "destino": "TRANSFERENCIA" if deposita else "EFECTIVO",
        },
    )


def registrar_gasto(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    return _bot(
        ctx,
        "REGISTRAR_GASTO",
        {
            "gastos": [
                {
                    "concepto": rng.choice(CONCEPTOS_GASTO),
                    "monto": float(_monto(rng, 500, 80_000)),
                    "moneda": "ARS",
                    "medio_pago": rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
                }
            ]
        },
    )


def consulta(ctx: Contexto) -> Resultado:
    """Las once consultas de lectura: no tocan nada y revientan igual."""
    rng = ctx.rng
    return _bot(
        ctx,
        "CONSULTA",
        {
            "tipo": rng.choice([
                "CARTERA", "VENTAS", "PASIVOS", "DEUDORES", "CLIENTE", "PRESTAMOS",
                "MOVIMIENTOS", "CAJA", "GASTOS", "DIVISAS", "RESUMEN",
            ]),
            "periodo": rng.choice(["HOY", "SEMANA", "MES", "TODO"]),
            "cliente_nombre": _nombre(rng),
        },
    )


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — deshacer y corregir (lo más peligroso que hay)
# ══════════════════════════════════════════════════════════════════════
#
# Estas tres son las que más veces rompieron cosas en la historia del proyecto,
# y por buenas razones: **rehacen asientos de caja ya escritos**. Anular tiene
# que barrer todas las líneas de la entidad —una `referencia_tipo` que falte en
# el catálogo las deja vivas contando plata que ya no existe—, revertir tiene que
# borrar el ingreso pero conservar el egreso de la compra, y editar rehace el
# asiento con los valores nuevos sin tocar los cobros que ya recibió.
#
# Sin estos escenarios, la mitad de los invariantes no se ejercita nunca: sin una
# sola anulación, `caja_sin_huerfanos` no puede encontrar nada y la sesión
# termina en verde sin haber mirado dónde más duele.

def _entidad_para_deshacer(ctx: Contexto) -> tuple[str, str] | None:
    """Algo vivo que se pueda deshacer, como lo nombraría el operador."""
    rng = ctx.rng
    opciones: list[tuple[str, str]] = []

    cheque = _uno_al_azar(
        ctx.db,
        sa.select(Cheque).where(Cheque.anulado_at.is_(None)).order_by(Cheque.created_at.desc()),
        rng,
    )
    if cheque is not None:
        opciones.append(("CHEQUE", cheque.nro_cheque))

    if _acreedor_con_deuda(ctx) is not None:
        opciones.append(("PASIVO", "ultimo"))

    prestamo = _uno_al_azar(
        ctx.db,
        sa.select(Cliente)
        .join(Prestamo, Prestamo.cliente_id == Cliente.id)
        .where(Prestamo.anulado_at.is_(None)),
        rng,
    )
    if prestamo is not None:
        opciones.append(("PRESTAMO", prestamo.nombre))

    opciones += [("GASTO", "ultimo"), ("MOVIMIENTO", "ultimo")]
    return rng.choice(opciones) if opciones else None


def anular_operacion(ctx: Contexto) -> Resultado:
    """Eliminar: da de baja la operación y **revierte su efecto en la caja**."""
    elegida = _entidad_para_deshacer(ctx)
    if elegida is None:
        return Resultado(ok=True, rechazo="no hay nada cargado para deshacer")
    tipo, identificador = elegida
    return _bot(ctx, "REVERTIR_OPERACION", {
        "accion": "ELIMINAR",
        "tipo_operacion": tipo,
        "identificador": identificador,
    })


def revertir_cheque(ctx: Contexto) -> Resultado:
    """Revertir: devuelve un cheque terminal a cartera **sin eliminarlo**.

    Borra el ingreso de la venta y conserva el egreso de la compra, que sigue
    siendo cierto. Es la única puerta que abre los estados terminales.
    """
    cheque = _uno_al_azar(
        ctx.db,
        sa.select(Cheque).where(
            Cheque.anulado_at.is_(None),
            Cheque.estado.in_(
                [ChequeEstado.VENDIDO, ChequeEstado.FIADO, ChequeEstado.COBRADO]
            ),
        ),
        ctx.rng,
    )
    if cheque is None:
        return Resultado(ok=True, rechazo="no hay cheques en estado terminal")
    return _bot(ctx, "REVERTIR_OPERACION", {
        "accion": "REVERTIR",
        "tipo_operacion": "CHEQUE",
        "identificador": cheque.nro_cheque,
    })


def editar_operacion(ctx: Contexto) -> Resultado:
    """Corregir un valor ya cargado: rehace el asiento de caja de esa entidad."""
    rng = ctx.rng
    cheque = _uno_al_azar(
        ctx.db,
        sa.select(Cheque).where(Cheque.anulado_at.is_(None)).order_by(Cheque.created_at.desc()),
        rng,
    )
    if cheque is None:
        return Resultado(ok=True, rechazo="no hay cheques para corregir")

    campo, valor = rng.choice([
        ("monto", float(_monto(rng, 50_000, 4_000_000))),
        ("porcentaje_compra", float(_porcentaje(rng))),
        ("fecha_pago", _fecha(rng, 0, 120).isoformat()),
        ("cliente_origen", _nombre(rng)),
    ])
    return _bot(ctx, "EDITAR_OPERACION", {
        "tipo_operacion": "CHEQUE",
        "identificador": cheque.nro_cheque,
        "campo": campo,
        "nuevo_valor": valor,
    })


def editar_gasto(ctx: Contexto) -> Resultado:
    """El gasto es el que más se corrige por chat: se carga rápido y mal."""
    return _bot(ctx, "EDITAR_OPERACION", {
        "tipo_operacion": "GASTO",
        "identificador": "ultimo",
        "campo": "monto",
        "nuevo_valor": float(_monto(ctx.rng, 500, 90_000)),
    })


# ══════════════════════════════════════════════════════════════════════
#  Escenarios — por el panel
# ══════════════════════════════════════════════════════════════════════

def panel_gasto(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    return _panel(ctx, "POST", "/gastos-operativos", {
        "concepto": rng.choice(CONCEPTOS_GASTO),
        "monto": str(_monto(rng, 500, 60_000)),
        "moneda": "ARS",
        "medio_pago": rng.choice(["EFECTIVO", "TRANSFERENCIA"]),
        "fecha_operacion": _fecha(rng, -20, 0).isoformat(),
    })


def panel_traspaso(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    deposita = rng.random() < 0.5
    return _panel(ctx, "POST", "/traspasos", {
        "monto": str(_monto(rng, 10_000, 800_000)),
        "moneda": "ARS",
        "origen": "EFECTIVO" if deposita else "TRANSFERENCIA",
        "destino": "TRANSFERENCIA" if deposita else "EFECTIVO",
    })


def panel_ajuste_caja(ctx: Contexto) -> Resultado:
    rng = ctx.rng
    moneda = rng.choice(["ARS", "ARS", "USD"])
    tipo = rng.choice(["INGRESO", "EGRESO"])
    payload: dict[str, Any] = {
        "fecha": _fecha(rng, -10, 0).isoformat(),
        "moneda": moneda,
        "tipo": tipo,
        "motivo": rng.choice(["CORRECCION", "APORTE", "RETIRO", "OTRO"]),
        "monto": str(_monto(rng, 1_000, 200_000)),
        # Un ajuste en dólares solo puede ser del efectivo: no hay cuenta en USD.
        "medio_pago": (
            "EFECTIVO" if moneda == "USD" else rng.choice(["EFECTIVO", "TRANSFERENCIA"])
        ),
        "descripcion": "ajuste de la sesión de carga",
        "operador_id": "carga",
    }
    if moneda == "USD" and tipo == "INGRESO":
        # Sumar dólares sin costo los dejaría en la caja sin poder venderse.
        payload["cotizacion_usd"] = str(_cotizacion(rng))
    return _panel(ctx, "POST", "/ajustes-caja", payload)


def panel_reportes(ctx: Contexto) -> Resultado:
    """Los reportes son de lectura, y son justo donde revienta lo mal cargado.

    Un reporte que explota es la peor cara del sistema: el operador no puede
    cerrar el día y el dato ya está adentro.
    """
    rng = ctx.rng
    desde = _fecha(rng, -60, -1)
    hasta = desde + timedelta(days=rng.randint(0, 45))
    ruta = rng.choice(["/reportes/caja", "/reportes/movimientos", "/reportes/cobros-cuotas"])
    return _panel(ctx, "GET", f"{ruta}?desde={desde}&hasta={hasta}")


def panel_listados(ctx: Contexto) -> Resultado:
    ruta = ctx.rng.choice([
        "/cheques", "/pasivos", "/fiados", "/deudas-simples", "/prestamos",
        "/clientes", "/movimientos-efectivo", "/gastos-operativos", "/traspasos",
    ])
    return _panel(ctx, "GET", ruta)


# ══════════════════════════════════════════════════════════════════════
#  El catálogo y sus pesos
# ══════════════════════════════════════════════════════════════════════

# El peso es cuántas veces más probable es un escenario que otro. Las altas
# pesan más que los cobros a propósito: sin cheques en cartera ni deudas vivas,
# la mitad del catálogo no tiene con qué operar y la sesión se pasa rechazando.
CATALOGO: tuple[tuple[str, Callable[[Contexto], Resultado], int], ...] = (
    ("registrar_cheque",         registrar_cheque,         10),
    ("vender_cheque",            vender_cheque,             6),
    ("fiar_cheque",              fiar_cheque,               4),
    ("cobrar_cheque",            cobrar_cheque,             3),
    ("registrar_deuda_cliente",  registrar_deuda_cliente,   6),
    ("registrar_deuda_negocio",  registrar_deuda_negocio,   6),
    ("cobrar_deuda_cliente",     cobrar_deuda_cliente,      8),
    ("pagar_pasivo",             pagar_pasivo,              5),
    ("compensar_deuda",          compensar_deuda,           3),
    ("nuevo_prestamo",           nuevo_prestamo,            5),
    ("cobrar_cuota",             cobrar_cuota,              6),
    ("operacion_divisas",        operacion_divisas,         8),
    ("traspaso_caja",            traspaso_caja,             4),
    ("registrar_gasto",          registrar_gasto,           6),
    ("consulta",                 consulta,                  8),
    # Deshacer y corregir: rehacen asientos de caja ya escritos. Pesan poco
    # porque en el negocio real son la excepción, pero sin ellas la mitad de los
    # invariantes no se ejercita nunca.
    ("anular_operacion",         anular_operacion,          4),
    ("revertir_cheque",          revertir_cheque,           3),
    ("editar_operacion",         editar_operacion,          4),
    ("editar_gasto",             editar_gasto,              3),
    ("panel_gasto",              panel_gasto,               3),
    ("panel_traspaso",           panel_traspaso,            2),
    ("panel_ajuste_caja",        panel_ajuste_caja,         3),
    ("panel_reportes",           panel_reportes,            6),
    ("panel_listados",           panel_listados,            4),
)

NOMBRES_ESCENARIOS = tuple(nombre for nombre, _, _ in CATALOGO)


def elegir(rng: random.Random) -> tuple[str, Callable[[Contexto], Resultado]]:
    """Un escenario al azar, respetando los pesos."""
    total = sum(peso for _, _, peso in CATALOGO)
    tirada = rng.uniform(0, total)
    acumulado = 0.0
    for nombre, funcion, peso in CATALOGO:
        acumulado += peso
        if tirada <= acumulado:
            return nombre, funcion
    return CATALOGO[-1][0], CATALOGO[-1][1]
