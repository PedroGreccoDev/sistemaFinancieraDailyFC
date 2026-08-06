"""apertura.py — Los saldos con los que el negocio arrancó a usar el sistema.

Régimen definido 2026-08-06. Cuando el sistema se puso en marcha el negocio ya
venía funcionando: había **efectivo en el cajón** y **cheques en cartera**
comprados tiempo atrás. Los dos son saldos de apertura, no operaciones del día.

Dos piezas, una sola idea:

1. **Fecha de corte.** Hasta esa fecha inclusive, los cheques que se cargan son
   inventario preexistente y NO asientan el egreso de compra. Esa plata salió
   antes de que el sistema existiera —y el efectivo inicial ya la tiene
   descontada—, así que asentarla la restaría dos veces. Es automático: no
   depende de que el operador tilde nada en cada alta.

2. **Saldo inicial.** El efectivo en mano al arrancar, por moneda, con la fecha
   a la que corresponde (no la fecha en que se tipeó: se puede cargar días
   después y el reporte igual cierra bien para atrás).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ConfiguracionApertura,
    Moneda,
    MovimientoCaja,
)
from app.services import caja as svc_caja
from app.services.exceptions import ConflictError, DatabaseWriteError, ValidationError

# La fila singleton siempre es la 1 (garantizado por CHECK en la BD).
_ID = 1

_REF_APERTURA = "apertura"


def get_configuracion(db: Session) -> ConfiguracionApertura:
    """Devuelve la configuración de apertura, creándola vacía si no existe.

    La migración inserta la fila, pero se crea acá también para que el arranque
    no dependa del orden de despliegue."""
    cfg = db.get(ConfiguracionApertura, _ID)
    if cfg is None:
        cfg = ConfiguracionApertura(id=_ID)
        db.add(cfg)
        db.flush()
    return cfg


def es_carga_inicial(db: Session, fecha: date) -> bool:
    """True si un cheque cargado en `fecha` es cartera preexistente.

    Lo consulta el alta de cheques (panel y bot) para decidir si asienta o no el
    egreso de compra. Sin fecha de corte definida, todo es operación normal."""
    cfg = db.get(ConfiguracionApertura, _ID)
    if cfg is None or cfg.fecha_corte_carga_inicial is None:
        return False
    return fecha <= cfg.fecha_corte_carga_inicial


# ══════════════════════════════════════════════════════════════════════
#  Fecha de corte
# ══════════════════════════════════════════════════════════════════════

def definir_fecha_corte(
    db: Session, fecha_corte: date, *, operador_id: str
) -> dict[str, int]:
    """Fija la fecha de corte y **corrige hacia atrás** lo ya cargado.

    Los cheques que se cargaron antes de que existiera esta configuración
    asentaron un egreso de compra que no correspondía. Al fijar el corte se los
    marca como carga inicial y se les borra esa línea de caja, para que la
    cartera preexistente deje de descontar plata que salió antes del sistema.

    Devuelve cuántos cheques se marcaron y cuántas líneas de caja se revirtieron.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador.")

    cfg = get_configuracion(db)

    try:
        cfg.fecha_corte_carga_inicial = fecha_corte

        # Cheques vivos cargados hasta el corte que todavía figuran como compra.
        cheques = list(
            db.scalars(
                select(Cheque).where(
                    Cheque.anulado_at.is_(None),
                    Cheque.es_carga_inicial.is_(False),
                )
            )
        )
        marcados = 0
        lineas = 0
        for cheque in cheques:
            if _fecha_carga(cheque) > fecha_corte:
                continue
            cheque.es_carga_inicial = True
            marcados += 1
            # Solo el egreso de COMPRA: si el cheque ya se vendió o cobró, ese
            # ingreso es plata real que entró y se conserva.
            lineas += _borrar_egreso_compra(db, cheque)

        db.commit()
        return {"cheques_marcados": marcados, "lineas_revertidas": lineas}
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo definir la fecha de corte.") from exc


def _fecha_carga(cheque: Cheque) -> date:
    """Día local en que el cheque entró al sistema."""
    from app.core.fechas import fecha_local

    return fecha_local(cheque.created_at)


def _borrar_egreso_compra(db: Session, cheque: Cheque) -> int:
    """Borra la línea COMPRA_CHEQUE del cheque. Devuelve cuántas borró."""
    egresos = list(
        db.scalars(
            select(MovimientoCaja).where(
                MovimientoCaja.referencia_tipo == "cheque",
                MovimientoCaja.referencia_id == cheque.id,
                MovimientoCaja.categoria == CajaCategoria.COMPRA_CHEQUE,
            )
        )
    )
    for mov in egresos:
        db.delete(mov)
    return len(egresos)


# ══════════════════════════════════════════════════════════════════════
#  Saldo inicial de efectivo
# ══════════════════════════════════════════════════════════════════════

def definir_saldo_inicial(
    db: Session,
    *,
    saldo_ars: Decimal,
    saldo_usd: Decimal,
    fecha: date,
    operador_id: str,
    forzar: bool = False,
) -> ConfiguracionApertura:
    """Carga el efectivo con el que arrancó el negocio. **Por única vez.**

    Asienta una línea `SALDO_INICIAL` por moneda en la fecha indicada —que es el
    día al que corresponde el efectivo, no el día en que se tipea—. El reporte la
    trata como saldo de apertura y no como ingreso del día, para no inflar el neto
    de la jornada en que se carga.

    `forzar` permite rehacerlo si se cargó mal: borra las líneas anteriores y las
    vuelve a asentar.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador.")
    if saldo_ars < 0 or saldo_usd < 0:
        raise ValidationError("Los saldos de apertura no pueden ser negativos.")

    cfg = get_configuracion(db)
    if cfg.saldo_definido and not forzar:
        raise ConflictError(
            f"El saldo de apertura ya fue definido el "
            f"{cfg.definido_at:%d/%m/%Y} por {cfg.definido_por}. "
            "Para corregirlo hay que rehacerlo explícitamente."
        )

    try:
        # Rehacer: se limpian las líneas previas para no duplicar la apertura.
        svc_caja.borrar_por_referencia_tipo(db, _REF_APERTURA)

        for moneda, monto in ((Moneda.ARS, saldo_ars), (Moneda.USD, saldo_usd)):
            if monto > 0:
                svc_caja.registrar(
                    db,
                    fecha=fecha,
                    moneda=moneda,
                    tipo=CajaTipo.INGRESO,
                    categoria=CajaCategoria.SALDO_INICIAL,
                    monto=monto,
                    referencia_tipo=_REF_APERTURA,
                    detalle="Saldo inicial de caja (efectivo al arrancar el sistema)",
                )

        cfg.saldo_inicial_ars = saldo_ars
        cfg.saldo_inicial_usd = saldo_usd
        cfg.fecha_saldo_inicial = fecha
        cfg.definido_por = operador_id.strip()
        cfg.definido_at = datetime.now(tz=UTC)

        db.commit()
        db.refresh(cfg)
        return cfg
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo definir el saldo de apertura.") from exc
