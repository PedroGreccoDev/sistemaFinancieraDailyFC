"""traspasos.py — Plata que pasa de una caja a la otra.

Depositar en el banco o sacar del cajero no es un ingreso ni un egreso del
negocio: la plata no entró ni salió, cambió de bolsillo. Pero **sí** mueve los
dos saldos paralelos, y en sentidos opuestos (§Caja paralela).

Por eso un traspaso son siempre **dos líneas** de caja con el mismo
`referencia_id`: el EGRESO de la caja de origen y el INGRESO de la de destino,
mismo monto y misma moneda. En el neto del día se cancelan solas —que es lo
correcto, no ganaste ni perdiste— pero cada saldo queda donde tiene que quedar.

Sin esta operación las dos cajas se despegan de la realidad el día que hacés el
primer depósito, y no hay forma de arreglarlo salvo dos ajustes a mano que el
reporte muestra como "corrección de descuadre".
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import (
    CajaCategoria,
    CajaTipo,
    MedioPago,
    Moneda,
    MovimientoCaja,
)
from app.services import caja as svc_caja
from app.services.exceptions import (
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_REF = "traspaso"
_CENTAVO = Decimal("0.01")


@dataclass
class Traspaso:
    """Un movimiento entre cajas, reconstruido desde sus dos líneas."""

    id: uuid.UUID
    fecha: date
    moneda: Moneda
    monto: Decimal
    origen: MedioPago
    destino: MedioPago
    detalle: str | None


def registrar(
    db: Session,
    *,
    monto: Decimal,
    moneda: Moneda = Moneda.ARS,
    origen: MedioPago,
    destino: MedioPago,
    fecha: date | None = None,
    detalle: str | None = None,
) -> Traspaso:
    """Pasa `monto` de una caja a la otra y devuelve el traspaso resultante.

    No toca el stock de dólares aunque la moneda sea USD: esos dólares ya eran
    del negocio antes y lo siguen siendo. El stock mide cuántos hay y a qué costo
    entraron, no en qué bolsillo están (§Stock de dólares).
    """
    if origen == destino:
        raise ValidationError(
            "El traspaso tiene que ir de una caja a la otra: elegí un origen y un "
            "destino distintos."
        )
    monto = Decimal(monto).quantize(_CENTAVO)
    if monto <= Decimal("0.00"):
        raise ValidationError("El monto del traspaso tiene que ser mayor a cero.")

    fecha = fecha or hoy_local()
    # Un id propio del traspaso enlaza las dos líneas: es lo que permite listarlo
    # como una sola operación y anularlo entero (nunca media).
    traspaso_id = uuid.uuid4()
    texto = detalle or _detalle_default(origen, destino)

    try:
        for tipo, medio in (
            (CajaTipo.EGRESO, origen),
            (CajaTipo.INGRESO, destino),
        ):
            svc_caja.registrar(
                db,
                fecha=fecha,
                moneda=moneda,
                tipo=tipo,
                categoria=CajaCategoria.TRASPASO_CAJA,
                monto=monto,
                medio_pago=medio,
                referencia_tipo=_REF,
                referencia_id=traspaso_id,
                detalle=texto,
            )
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo registrar el traspaso.") from exc

    return Traspaso(
        id=traspaso_id,
        fecha=fecha,
        moneda=moneda,
        monto=monto,
        origen=origen,
        destino=destino,
        detalle=texto,
    )


def _detalle_default(origen: MedioPago, destino: MedioPago) -> str:
    """El nombre que le pone el operador a la operación, según hacia dónde va."""
    if origen == MedioPago.EFECTIVO:
        return "Depósito en cuenta"
    return "Extracción de la cuenta"


def listar(
    db: Session, desde: date | None = None, hasta: date | None = None
) -> list[Traspaso]:
    """Los traspasos del período, uno por operación (no dos por sus líneas)."""
    stmt = select(MovimientoCaja).where(
        MovimientoCaja.categoria == CajaCategoria.TRASPASO_CAJA,
        MovimientoCaja.referencia_tipo == _REF,
    )
    if desde is not None:
        stmt = stmt.where(MovimientoCaja.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(MovimientoCaja.fecha <= hasta)
    stmt = stmt.order_by(MovimientoCaja.fecha.desc(), MovimientoCaja.created_at.desc())

    por_id: dict[uuid.UUID, list[MovimientoCaja]] = {}
    for mov in db.scalars(stmt):
        if mov.referencia_id is not None:
            por_id.setdefault(mov.referencia_id, []).append(mov)

    traspasos: list[Traspaso] = []
    for tid, lineas in por_id.items():
        salida = next((m for m in lineas if m.tipo == CajaTipo.EGRESO), None)
        entrada = next((m for m in lineas if m.tipo == CajaTipo.INGRESO), None)
        # Media línea suelta no es un traspaso: se saltea en vez de inventar el
        # lado que falta, que mostraría una caja moviéndose sola.
        if salida is None or entrada is None:
            continue
        traspasos.append(
            Traspaso(
                id=tid,
                fecha=salida.fecha,
                moneda=salida.moneda,
                monto=salida.monto,
                origen=salida.medio_pago,
                destino=entrada.medio_pago,
                detalle=salida.detalle,
            )
        )
    traspasos.sort(key=lambda t: t.fecha, reverse=True)
    return traspasos


def anular(db: Session, traspaso_id: uuid.UUID) -> None:
    """Borra el traspaso entero: las dos líneas o ninguna.

    Un traspaso no deja rastro fuera de la caja —no hay entidad de negocio
    detrás— así que borrarlo es deshacerlo. Borrar una sola línea dejaría plata
    apareciendo o desapareciendo de la nada en uno de los dos saldos.
    """
    lineas = list(
        db.scalars(
            select(MovimientoCaja).where(
                MovimientoCaja.categoria == CajaCategoria.TRASPASO_CAJA,
                MovimientoCaja.referencia_tipo == _REF,
                MovimientoCaja.referencia_id == traspaso_id,
            )
        )
    )
    if not lineas:
        raise NotFoundError(f"Traspaso {traspaso_id} no encontrado.")
    try:
        for linea in lineas:
            db.delete(linea)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo anular el traspaso.") from exc
