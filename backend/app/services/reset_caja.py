"""reset_caja.py — Vaciar el libro de caja sin perder lo que se debe.

**Esta operación borra datos y no se puede deshacer.** Existe para un momento
puntual: arrancar la caja de cero con saldos contados de verdad, cuando la
historia acumulada ya no representa lo que hay en el cajón ni en el banco.

**Qué se lleva** — todo lo que *es* caja:

- `movimientos_caja`: el libro entero.
- `movimientos_efectivo`: los lotes de dólares. El stock se rearma desde el saldo
  inicial nuevo; dejarlos sería contar dos veces los mismos dólares.
- `ajustes_caja` y `gastos_operativos`: existen **solo** como movimiento de caja.
  Conservarlos con su línea borrada los dejaría de adorno, sumando en ningún lado.

**Qué NO se toca** — lo que el negocio sigue teniendo o debiendo:

- Los **cheques** en cartera, con su estado y su historia.
- Lo que los **clientes deben**: préstamos, cuotas, fiados y deudas libres.
- Los **pasivos**: lo que el negocio debe.
- Las **compensaciones** (que nunca movieron la caja), los clientes y los usuarios.

Un cheque vendido queda vendido aunque su ingreso ya no esté en el libro, igual
que la cartera preexistente de la puesta en marcha (§Apertura): esa plata entró
antes del corte, y el saldo inicial que se cargue después **ya la tiene adentro**.

**Además mueve la línea de corte**, y sin esa parte el reset no sirve. Editar un
cheque, un préstamo o una deuda **rehace su asiento de caja**: sin corte, corregir
el banco de un cheque comprado hace tres meses le resucita el egreso dentro de la
caja recién estrenada. El operador tocó un dato menor y el saldo se movió solo,
sin ninguna señal. Es el mismo problema que la cartera preexistente de la puesta
en marcha (§Apertura), un mes después.

La línea se pone **por estado, no por fecha**: se marca como preexistente todo lo
que está cargado en el momento de ejecutarlo, y el corte queda en el día
**anterior**. Así lo que se cargue después —incluso ese mismo día— es operación
normal y descuenta como corresponde. El operador no tiene que elegir ninguna
fecha, que es justo donde se equivocaría: un corte puesto "hoy" haría que las
compras reales del día no descontaran plata.

Después de correrlo hay que cargar la apertura (`svc_apertura.definir_saldo_inicial`
con `forzar=True`) con los cuatro saldos contados: billetes y banco, por moneda.
Sin eso las dos cajas arrancan en cero.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import (
    AjusteCaja,
    Cheque,
    ConfiguracionApertura,
    GastoOperativo,
    MovimientoCaja,
    MovimientoEfectivo,
    Pasivo,
)
from app.services.exceptions import DatabaseWriteError, ValidationError

# Frase exacta que hay que escribir para ejecutarlo. No es burocracia: es la
# diferencia entre un click de más y borrar el libro de caja de producción.
CONFIRMACION = "RESETEAR CAJA"


@dataclass
class ResetCajaResumen:
    """Cuántas filas se borran (o se borraron) de cada tabla."""

    movimientos_caja: int = 0
    movimientos_efectivo: int = 0
    ajustes_caja: int = 0
    gastos_operativos: int = 0
    # Cheques que pasan a contar como preexistentes: quedan en cartera igual,
    # pero dejan de poder resucitar su egreso de compra al editarlos.
    cheques_marcados: int = 0
    fecha_corte: date | None = None
    conserva: dict[str, int] = field(default_factory=dict)


def _contar(db: Session, modelo) -> int:
    return int(db.scalar(select(func.count()).select_from(modelo)) or 0)


def _cheques_a_marcar(db: Session) -> list[Cheque]:
    """Los cheques vivos que todavía figuran como compra normal.

    Son los que hay que dejar del lado viejo de la línea: siguen en cartera con
    su estado y su historia, pero su egreso de compra ya no se puede rehacer.
    """
    return list(
        db.scalars(
            select(Cheque).where(
                Cheque.anulado_at.is_(None),
                Cheque.es_carga_inicial.is_(False),
            )
        )
    )


def previsualizar(db: Session) -> ResetCajaResumen:
    """Qué se borraría y qué se conserva. **No toca nada.**

    Es obligatorio mirarlo antes: el resumen es la única oportunidad de descubrir
    que hay algo cargado que no se esperaba.
    """
    from app.db.models import DeudaSimple, Fiado, Prestamo

    return ResetCajaResumen(
        movimientos_caja=_contar(db, MovimientoCaja),
        movimientos_efectivo=_contar(db, MovimientoEfectivo),
        ajustes_caja=_contar(db, AjusteCaja),
        gastos_operativos=_contar(db, GastoOperativo),
        cheques_marcados=len(_cheques_a_marcar(db)),
        fecha_corte=hoy_local() - timedelta(days=1),
        conserva={
            "cheques": _contar(db, Cheque),
            "prestamos": _contar(db, Prestamo),
            "fiados": _contar(db, Fiado),
            "deudas_simples": _contar(db, DeudaSimple),
            "pasivos": _contar(db, Pasivo),
        },
    )


def ejecutar(db: Session, *, operador_id: str, confirmacion: str) -> ResetCajaResumen:
    """Vacía el libro de caja y el stock de dólares. **Irreversible.**

    Exige la frase exacta de `CONFIRMACION`: un booleano `forzar=true` se manda
    por accidente desde un cliente HTTP, una frase escrita a mano no.
    """
    if not (operador_id and operador_id.strip()):
        raise ValidationError("Se requiere identificar al operador.")
    if confirmacion.strip().upper() != CONFIRMACION:
        raise ValidationError(
            f"Para resetear la caja hay que escribir exactamente '{CONFIRMACION}'. "
            "Es una operación que borra el libro entero y no se puede deshacer."
        )

    resumen = previsualizar(db)
    # El corte va en el día ANTERIOR: lo que se cargue hoy después de esto —una
    # compra real, el primer cobro— tiene que descontar como cualquier otra
    # operación. Un corte puesto "hoy" dejaría todo el día del otro lado.
    corte = hoy_local() - timedelta(days=1)
    try:
        # Los pasivos apuntan a su lote de stock por FK (§5): sin soltar el
        # vínculo primero, borrar los lotes falla y el reset queda a medias.
        db.execute(update(Pasivo).values(lote_id=None))
        # Los ajustes también cuelgan de su lote, y encima son caja: se van.
        db.execute(delete(AjusteCaja))
        db.execute(delete(GastoOperativo))
        db.execute(delete(MovimientoEfectivo))
        db.execute(delete(MovimientoCaja))

        # La apertura vuelve a estar sin definir: los saldos viejos ya no
        # describen nada y dejarlos marcados haría que cargar los nuevos exija
        # `forzar`, como si se estuviera corrigiendo un error.
        # La línea se mueve por ESTADO, no por fecha: se marca lo que está
        # cargado en este instante. Un cheque que se cargue después queda del
        # lado nuevo aunque su fecha de compra sea vieja, que es lo correcto —el
        # que decide de qué lado está es el momento de apretar el botón.
        for cheque in _cheques_a_marcar(db):
            cheque.es_carga_inicial = True

        # `get_configuracion` la crea si no existe. Con un `select` a secas, una
        # base sin configuración dejaba el corte SIN FIJAR: los cheques quedaban
        # marcados —tienen su propia marca— pero préstamos, deudas y pasivos
        # volvían a asentar su egreso al editarlos, que es justo el agujero que
        # este corte viene a tapar.
        from app.services.apertura import get_configuracion

        cfg = get_configuracion(db)
        if cfg is not None:
            cfg.fecha_corte_carga_inicial = corte
            cfg.saldo_inicial_ars = None
            cfg.saldo_inicial_usd = None
            cfg.saldo_inicial_ars_transf = None
            cfg.saldo_inicial_usd_transf = None
            cfg.cotizacion_usd_inicial = None
            cfg.fecha_saldo_inicial = None
            cfg.definido_por = None
            cfg.definido_at = None

        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo resetear la caja.") from exc

    resumen.fecha_corte = corte
    return resumen
