"""Lo que tiene que ser cierto siempre, pase lo que pase.

Un error que revienta se ve: hay excepción, hay traceback, hay bug. **El error
que importa de verdad es el que no revienta**: el bot contesta "listo", el panel
muestra su cartel verde, y la caja quedó cinco mil pesos abajo. Eso no da
ninguna señal hasta que alguien cuenta billetes al cierre del mes y no le da.

Estas funciones son esa señal. Se corren después de cada operación de la sesión
de carga y preguntan cosas que el negocio no puede desmentir: que no haya deudas
en negativo, que un fiado cancelado no siga debiendo, que anular haya barrido
sus líneas de caja. Un invariante roto **es un bug con número aunque no haya
explotado nada**.

Sobre el diseño: cada chequeo es una consulta agregada y no un recorrido en
Python. Se corren miles de veces y tienen que costar milisegundos, o la sesión
tardaría más en verificar que en operar.

Ver §Sesión de carga.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.orm import Session


@dataclass
class Violacion:
    """Un invariante que no se cumple. Es un bug, aunque nada haya fallado."""

    # Identidad estable del invariante: es lo que agrupa el bug. Dos violaciones
    # del mismo invariante con distinta entidad son el mismo problema.
    clave:   str
    titulo:  str
    detalle: str


def _filas(db: Session, sql: str) -> list:
    return list(db.execute(sa.text(sql)).all())


# ══════════════════════════════════════════════════════════════════════
#  Plata que aparece de la nada
# ══════════════════════════════════════════════════════════════════════

def saldos_no_negativos(db: Session) -> list[Violacion]:
    """Ninguna deuda puede deber menos que nada.

    Un saldo negativo es plata inventada: significa que se imputó más de lo que
    se debía y el sistema lo aceptó. Nadie lo ve —las pantallas muestran el
    número tal cual— y al sumar el total de deudores da de menos.
    """
    violaciones = []
    for tabla, entidad in (
        ("fiados", "fiado"),
        ("deudas_simples", "deuda simple"),
        ("pasivos", "pasivo"),
    ):
        malos = _filas(
            db,
            f"SELECT id, saldo_pendiente FROM {tabla} "
            f"WHERE saldo_pendiente < 0 AND anulado_at IS NULL LIMIT 5",
        )
        for fila in malos:
            violaciones.append(
                Violacion(
                    clave=f"saldo-negativo-{tabla}",
                    titulo=f"Un {entidad} quedó con saldo negativo",
                    detalle=(
                        f"{tabla}.id={fila.id} tiene saldo_pendiente="
                        f"{fila.saldo_pendiente}. Se imputó más de lo que se debía: "
                        "es plata que el sistema inventó y que resta del total de "
                        "deudores sin que nada falle."
                    ),
                )
            )
    return violaciones


def cuotas_sin_sobrepago(db: Session) -> list[Violacion]:
    """Una cuota no puede tener pagado más de lo que vale."""
    malas = _filas(
        db,
        "SELECT c.id, c.monto, c.monto_pagado FROM cuotas c "
        "JOIN prestamos p ON p.id = c.prestamo_id "
        "WHERE c.monto_pagado > c.monto AND p.anulado_at IS NULL LIMIT 5",
    )
    return [
        Violacion(
            clave="cuota-sobrepagada",
            titulo="Una cuota tiene pagado más de lo que vale",
            detalle=(
                f"cuotas.id={f.id} monto={f.monto} monto_pagado={f.monto_pagado}. "
                "El excedente no fue a ninguna otra cuota ni volvió al cliente: "
                "quedó adentro de esta y el préstamo muestra menos deuda de la real."
            ),
        )
        for f in malas
    ]


# ══════════════════════════════════════════════════════════════════════
#  Estados que dicen una cosa y los números otra
# ══════════════════════════════════════════════════════════════════════

def estados_coherentes(db: Session) -> list[Violacion]:
    """Una deuda cancelada no puede seguir debiendo, ni al revés.

    Es el desacople más traicionero: la pantalla de deudores lee el **estado**
    para decidir si la lista, pero los totales suman el **saldo**. Cuando se
    separan, el cliente desaparece de la lista con plata todavía adeudada, o
    aparece debiendo cero.
    """
    violaciones = []
    casos = (
        ("fiados", "CANCELADO", "fiado"),
        ("deudas_simples", "CANCELADA", "deuda simple"),
        ("pasivos", "CANCELADA", "pasivo"),
    )
    for tabla, cancelado, entidad in casos:
        cerrados_con_saldo = _filas(
            db,
            f"SELECT id, saldo_pendiente FROM {tabla} "
            f"WHERE estado = '{cancelado}' AND saldo_pendiente > 0 "
            f"AND anulado_at IS NULL LIMIT 5",
        )
        for f in cerrados_con_saldo:
            violaciones.append(
                Violacion(
                    clave=f"cancelado-con-saldo-{tabla}",
                    titulo=f"Un {entidad} figura cancelado pero sigue debiendo",
                    detalle=(
                        f"{tabla}.id={f.id} estado={cancelado} "
                        f"saldo_pendiente={f.saldo_pendiente}. Sale de los listados "
                        "por el estado y sigue sumando en los totales por el saldo."
                    ),
                )
            )

        abiertos_sin_saldo = _filas(
            db,
            f"SELECT id FROM {tabla} "
            f"WHERE estado <> '{cancelado}' AND saldo_pendiente = 0 "
            f"AND anulado_at IS NULL LIMIT 5",
        )
        for f in abiertos_sin_saldo:
            violaciones.append(
                Violacion(
                    clave=f"abierto-sin-saldo-{tabla}",
                    titulo=f"Un {entidad} quedó abierto con saldo cero",
                    detalle=(
                        f"{tabla}.id={f.id} no debe nada y sigue abierto. La última "
                        "imputación lo saldó pero no lo cerró: queda listado como "
                        "deuda viva para siempre."
                    ),
                )
            )
    return violaciones


# ══════════════════════════════════════════════════════════════════════
#  El libro de caja
# ══════════════════════════════════════════════════════════════════════

def caja_sin_huerfanos(db: Session) -> list[Violacion]:
    """Anular una operación tiene que llevarse sus líneas de caja.

    Si quedan, esa plata sigue contando en el reporte del día aunque la
    operación ya no exista. El motor de anulación barre por `referencia_tipo` y
    un tipo que falte en su catálogo deja las líneas vivas **sin fallar** — es el
    agujero que el propio `test_anulacion.py` custodia, acá visto desde los datos.
    """
    violaciones = []
    # (referencia_tipo del libro, tabla de la entidad)
    familias = (
        ("cheque", "cheques"),
        ("prestamo", "prestamos"),
        ("fiado", "fiados"),
        ("deuda_simple", "deudas_simples"),
        ("pasivo", "pasivos"),
        ("gasto", "gastos_operativos"),
        ("movimiento", "movimientos_efectivo"),
        ("ajuste_caja", "ajustes_caja"),
    )
    for referencia, tabla in familias:
        huerfanas = _filas(
            db,
            f"SELECT mc.id, mc.referencia_id, mc.monto, mc.categoria "
            f"FROM movimientos_caja mc "
            f"JOIN {tabla} e ON e.id = mc.referencia_id "
            f"WHERE mc.referencia_tipo = '{referencia}' "
            f"AND e.anulado_at IS NOT NULL LIMIT 5",
        )
        for f in huerfanas:
            violaciones.append(
                Violacion(
                    clave=f"caja-huerfana-{referencia}",
                    titulo=f"Quedó una línea de caja de un {referencia} anulado",
                    detalle=(
                        f"movimientos_caja.id={f.id} categoria={f.categoria} "
                        f"monto={f.monto} apunta a {tabla}.id={f.referencia_id}, que "
                        "está anulado. Esa plata sigue contando en el reporte del día."
                    ),
                )
            )
    return violaciones


def caja_usd_contra_stock(db: Session) -> list[Violacion]:
    """Los dólares de la caja tienen que ser los mismos que los del stock.

    Desde §Stock de dólares **toda** entrada o salida de dólares mueve las dos
    cosas: la caja dice cuántos hay, los lotes dicen cuántos quedan por vender.
    Si se separan, una de las dos miente — y la que miente decide: con el stock
    corto la venta falla con "no hay stock" teniendo los billetes en la mano, y
    con el stock largo se vende a un costo que no existió y la ganancia sale mal.

    Es el invariante que cruza dos caminos distintos, así que es el que puede
    encontrar algo que ningún test unitario ve. También es el más frágil de la
    lista: si aparece una operación legítima que mueva una sola de las dos, esto
    va a marcar un falso positivo — y eso también hay que saberlo.
    """
    caja = db.execute(
        sa.text(
            "SELECT COALESCE(SUM(CASE WHEN tipo = 'INGRESO' THEN monto ELSE -monto END), 0) "
            "FROM movimientos_caja WHERE moneda = 'USD'"
        )
    ).scalar_one()
    stock = db.execute(
        sa.text(
            "SELECT COALESCE(SUM(usd_restante), 0) FROM movimientos_efectivo "
            "WHERE anulado_at IS NULL AND usd_restante > 0"
        )
    ).scalar_one()

    if Decimal(caja) == Decimal(stock):
        return []

    return [
        Violacion(
            clave="caja-usd-vs-stock",
            titulo="La caja en dólares no coincide con el stock vendible",
            detalle=(
                f"La caja USD dice {caja} y los lotes con stock suman {stock} "
                f"(diferencia: {Decimal(caja) - Decimal(stock)}).\n\n"
                "Una de las dos miente. Con el stock corto, vender falla con «no "
                "hay stock» teniendo los billetes; con el stock largo, se vende "
                "contra un costo que nunca existió y la ganancia sale mal."
            ),
        )
    ]


def lotes_coherentes(db: Session) -> list[Violacion]:
    """Un lote no puede tener más restante de lo que se compró, ni menos que cero."""
    malos = _filas(
        db,
        "SELECT id, monto, usd_restante FROM movimientos_efectivo "
        "WHERE anulado_at IS NULL AND (usd_restante < 0 OR usd_restante > monto) LIMIT 5",
    )
    return [
        Violacion(
            clave="lote-fifo-incoherente",
            titulo="Un lote de dólares tiene un restante imposible",
            detalle=(
                f"movimientos_efectivo.id={f.id} monto={f.monto} "
                f"usd_restante={f.usd_restante}. La cadena FIFO quedó mal imputada: "
                "las ventas que salgan de este lote van a calcular la ganancia "
                "contra un costo equivocado."
            ),
        )
        for f in malos
    ]


def traspasos_completos(db: Session) -> list[Violacion]:
    """Un traspaso entre cajas son dos líneas o ninguna.

    Media línea suelta es una caja moviéndose sola: la plata desaparece de un
    libro sin aparecer en el otro, y el neto del día queda corrido por el monto
    entero.
    """
    sueltos = _filas(
        db,
        "SELECT referencia_id, COUNT(*) AS n, SUM(CASE WHEN tipo='INGRESO' THEN 1 ELSE -1 END) AS balance "
        "FROM movimientos_caja WHERE categoria = 'TRASPASO_CAJA' "
        "GROUP BY referencia_id HAVING COUNT(*) <> 2 OR SUM(CASE WHEN tipo='INGRESO' THEN 1 ELSE -1 END) <> 0 "
        "LIMIT 5",
    )
    return [
        Violacion(
            clave="traspaso-a-medias",
            titulo="Un traspaso entre cajas quedó a medias",
            detalle=(
                f"referencia_id={f.referencia_id} tiene {f.n} línea(s) "
                f"(balance ingreso/egreso: {f.balance}). Un traspaso son siempre dos "
                "que se cancelan: el egreso de una caja y el ingreso de la otra."
            ),
        )
        for f in sueltos
    ]


def caja_con_medio(db: Session) -> list[Violacion]:
    """Toda línea del libro pertenece a una de las dos cajas.

    La columna es NOT NULL desde la `0026`, así que esto solo puede saltar si
    alguien afloja la restricción. Cuesta una consulta y custodia el régimen
    entero de §Las dos cajas: una línea sin medio no está en ningún saldo.
    """
    cuantas = db.execute(
        sa.text("SELECT COUNT(*) FROM movimientos_caja WHERE medio_pago IS NULL")
    ).scalar_one()
    if not cuantas:
        return []
    return [
        Violacion(
            clave="caja-sin-medio",
            titulo="Hay líneas de caja sin medio de pago",
            detalle=(
                f"{cuantas} línea(s) con medio_pago NULL. No pertenecen ni al "
                "efectivo ni a la transferencia: no las cuenta ningún saldo, y el "
                "descuadre solo aparece cuando alguien cuenta billetes."
            ),
        )
    ]


# El catálogo. **Un invariante nuevo se da de alta acá**, o no se corre nunca.
TODOS = (
    saldos_no_negativos,
    cuotas_sin_sobrepago,
    estados_coherentes,
    caja_sin_huerfanos,
    caja_usd_contra_stock,
    lotes_coherentes,
    traspasos_completos,
    caja_con_medio,
)


def verificar(db: Session) -> list[Violacion]:
    """Corre todos los invariantes y devuelve lo que no se cumple.

    Un invariante que revienta **no puede frenar la sesión**: se convierte en
    violación y la corrida sigue. Si una consulta falla porque la base quedó en
    un estado raro, eso también es información.
    """
    encontradas: list[Violacion] = []
    for chequeo in TODOS:
        try:
            encontradas += chequeo(db)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            encontradas.append(
                Violacion(
                    clave=f"invariante-roto-{chequeo.__name__}",
                    titulo=f"El invariante «{chequeo.__name__}» no se pudo verificar",
                    detalle=f"{type(exc).__name__}: {exc}",
                )
            )
    return encontradas
