from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import false as sa_false, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cliente,
    Cheque,
    ChequeEstado,
    ChequeTipo,
    Fiado,
    FiadoEstado,
    InvalidChequeStateTransition,
    ManualOperationRequired,
    MedioPago,
    Moneda,
)
from app.core.fechas import fecha_local, hoy_local
from app.schemas.cheques import (
    ChequeCreate,
    ChequeFiarRequest,
    ChequeManualTransition,
    ChequeUpdate,
)
from app.services import apertura as svc_apertura
from app.services import caja as svc_caja
from app.services import pasivos as svc_pasivos
from app.services.exceptions import (
    ConflictError,
    DatabaseWriteError,
    NotFoundError,
    ValidationError,
)

_CIEN = Decimal("100")


def describir(cheque: Cheque, con_monto: bool = True) -> str:
    """Cómo se nombra un cheque en un texto para el operador (caja, avisos, errores).

    Sale de un solo lado porque el número puede faltar —un e-cheq cargado desde un
    comprobante de emisión no lo trae (§E-cheq)—, y sin esto cada call site
    escribiría "cheque Nº None" a su manera. Cuando no hay número se lo nombra por
    lo que sí tiene, que es lo que le permite al operador reconocerlo en el panel.

    `con_monto=False` es para las listas que ya muestran el monto en su propia
    columna, donde repetirlo queda como "e-cheq sin número ($3.000.000,00) |
    $3.000.000,00". El nombre lo sigue decidiendo esta función y no el call site,
    que es todo el punto de que exista.
    """
    banco_txt = f" — {cheque.banco}" if cheque.banco else ""
    clase = "e-cheq" if cheque.tipo == ChequeTipo.ELECTRONICO else "cheque"
    if cheque.nro_cheque:
        return f"{clase} Nº {cheque.nro_cheque}{banco_txt}"
    monto_txt = f" (${cheque.monto:,.2f})" if con_monto else ""
    return f"{clase} sin número{monto_txt}{banco_txt}"


def _nombre_vendedor(db: Session, cliente_id: uuid.UUID | None) -> str:
    """A nombre de quién queda el pasivo de un cheque comprado a deber.

    El schema ya exige el vendedor cuando el cheque queda debido; esto solo
    resuelve su nombre, que es lo que guarda el pasivo (`acreedor` es texto: se
    le puede deber a alguien que no es cliente del sistema)."""
    cliente = db.get(Cliente, cliente_id) if cliente_id is not None else None
    if cliente is None:
        raise ValidationError(
            "Un cheque comprado a deber necesita el vendedor: indicá a quién le "
            "quedás debiendo."
        )
    return cliente.nombre


def create_cheque(
    db: Session,
    payload: ChequeCreate,
    created_at: datetime | None = None,
    foto: bytes | None = None,
    foto_mime: str | None = None,
) -> Cheque:
    # `medio_pago` es de la caja, no del cheque: se saca del payload antes de
    # construir el modelo o SQLAlchemy lo rechaza por columna inexistente.
    datos = payload.model_dump()
    medio_compra = datos.pop("medio_pago", MedioPago.EFECTIVO)
    cheque = Cheque(
        **datos,
        estado=ChequeEstado.EN_CARTERA,
        foto=foto,
        foto_mime=foto_mime,
    )
    if created_at is not None:
        cheque.created_at = created_at

    # Cartera preexistente: si la fecha cae dentro del período de carga inicial,
    # el cheque ya estaba comprado antes de que el sistema existiera y NO asienta
    # el egreso — esa plata salió fuera del período que la caja cubre, y el saldo
    # de apertura ya la tiene descontada. Ver services/apertura.py.
    fecha_carga = fecha_local(created_at)
    cheque.es_carga_inicial = svc_apertura.es_carga_inicial(db, fecha_carga)

    try:
        db.add(cheque)
        db.flush()
        # Comprar el cheque saca plata de la caja ARS: lo pagado = monto·(1−%compra).
        pagado = (cheque.monto * (_CIEN - cheque.porcentaje_compra) / _CIEN).quantize(Decimal("0.01"))
        detalle = f"Compra {describir(cheque)}"
        abonado, a_deber = svc_pasivos.repartir_compra(pagado, cheque.monto_abonado)

        if abonado > 0 and not cheque.es_carga_inicial:
            svc_caja.registrar(
                db, fecha=fecha_local(created_at), moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
                categoria=CajaCategoria.COMPRA_CHEQUE, monto=abonado,
                medio_pago=medio_compra,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=detalle if a_deber <= 0 else f"{detalle} (pago parcial)",
            )
        if a_deber > 0:
            # El pasivo se crea aunque sea carga inicial. La fecha de corte decide
            # si sale plata de la caja —la cartera vieja ya está descontada del
            # saldo de apertura—, no si la deuda existe: si no se pagó, se debe.
            svc_pasivos.crear_por_compra(
                db,
                acreedor=_nombre_vendedor(db, cheque.cliente_origen_id),
                concepto=f"{detalle} al {cheque.porcentaje_compra}%",
                monto=a_deber,
                moneda=Moneda.ARS,
                origen_tipo="cheque",
                origen_id=cheque.id,
            )
        db.commit()
        db.refresh(cheque)
        return cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(_msg_duplicado(db, payload.nro_cheque, payload.banco)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo crear el cheque.") from exc


def _mismo_papel(nro_cheque: str | None, banco: str | None):
    """Criterio de "es la misma lámina": mismo número y mismo banco.

    `banco` NULL se compara como cadena vacía, igual que el índice único
    (migración 0028): en Postgres NULL ≠ NULL, así que comparar la columna cruda
    dejaría fuera justo a los cheques sin banco —que son los que más necesitan
    que alguien los mire—.

    El **número** no recibe ese trato, a propósito: dos cheques sin número son
    cheques distintos, no el mismo dos veces (§0030). Sin número no hay con qué
    afirmar que son la misma lámina, así que no se comparan entre sí."""
    if not nro_cheque:
        # `false()` en vez de una comparación con NULL: deja explícito que "sin
        # número no matchea con nada", incluido otro sin número.
        return (sa_false(),)
    return (
        Cheque.nro_cheque == nro_cheque,
        func.coalesce(Cheque.banco, "") == (banco or ""),
    )


def pasadas_anteriores(
    db: Session,
    nro_cheque: str | None,
    banco: str | None,
    excluir_id: uuid.UUID | None = None,
) -> list[Cheque]:
    """Vueltas anteriores de este mismo cheque por el negocio, de la más vieja a la más nueva.

    Un cheque vendido sigue girando en plaza y puede volver: recomprarlo es una
    compra nueva y real, y cada pasada es una fila propia (§Recompra). Esto
    devuelve las pasadas que ya cerraron, para poder avisarle al operador que el
    papel que tiene en la mano ya pasó por acá.

    No filtra por estado a propósito: si hubiera otra pasada EN CARTERA, el índice
    único ya la habría frenado, y si igual existiera es justo lo que hay que
    mostrar."""
    query = select(Cheque).where(
        *_mismo_papel(nro_cheque, banco),
        Cheque.anulado_at.is_(None),
    )
    if excluir_id is not None:
        query = query.where(Cheque.id != excluir_id)
    return list(db.scalars(query.order_by(Cheque.created_at)))


def verificar_no_esta_en_cartera(db: Session, nro_cheque: str | None, banco: str | None) -> None:
    """Corta si ese mismo papel YA está en cartera. Usado al recibir un cheque como pago.

    Cuando un cheque entra pagando una deuda no pasa por `create_cheque` (recibirlo
    no es comprarlo), así que no lo cubre el índice único hasta el commit. Estos
    call sites lo chequean antes para poder dar un mensaje claro en vez de un
    IntegrityError.

    **Solo mira la cartera**, no todos los cheques vivos: un cheque que ya se vendió
    puede volver por el circuito y entrar de nuevo como pago (§Recompra). Lo único
    imposible es tener el mismo papel dos veces en cartera a la vez."""
    existente = db.scalar(
        select(Cheque).where(
            *_mismo_papel(nro_cheque, banco),
            Cheque.anulado_at.is_(None),
            Cheque.estado == ChequeEstado.EN_CARTERA,
        )
    )
    if existente is None:
        return
    banco_txt = f" del banco {existente.banco}" if existente.banco else " (sin banco)"
    fecha = existente.created_at.strftime("%d/%m/%y") if existente.created_at else "—"
    raise ConflictError(
        f"El cheque Nº {existente.nro_cheque}{banco_txt} ya está en cartera "
        f"(${existente.monto:,.2f}, cargado el {fecha}). "
        "Si es otro cheque distinto, indicá el banco para diferenciarlos."
    )


def _msg_duplicado(db: Session, nro_cheque: str | None, banco: str | None) -> str:
    """Mensaje informativo cuando choca la unicidad (banco, nro_cheque) en cartera.

    Desde la migración 0028 la unicidad solo rige entre los cheques EN CARTERA, así
    que llegar acá significa una cosa sola: **ese mismo papel ya está en cartera**.
    No es la recompra —esa pasa sin problema cuando la pasada anterior cerró—, es el
    duplicado real: cargar dos veces el cheque que se tiene en la mano."""
    existente = db.scalar(
        select(Cheque).where(
            *_mismo_papel(nro_cheque, banco),
            Cheque.anulado_at.is_(None),
            Cheque.estado == ChequeEstado.EN_CARTERA,
        )
    )
    if existente is None:
        return "Ya existe un cheque con ese número y banco en cartera."

    fecha = existente.created_at.strftime("%d/%m/%y") if existente.created_at else "—"
    if existente.banco:
        return (
            f"El cheque Nº {existente.nro_cheque} del banco {existente.banco} ya está "
            f"en cartera: ${existente.monto:,.2f}, cargado el {fecha}. "
            "Si ya lo vendiste y lo estás recomprando, registrá primero esa venta."
        )
    # Sin banco no hay con qué distinguir dos láminas homónimas, y la salida es
    # justo el dato que falta: cargarle el banco a alguna de las dos.
    return (
        f"Ya hay un cheque Nº {existente.nro_cheque} sin banco en cartera: "
        f"${existente.monto:,.2f}, cargado el {fecha}. "
        "Si es otro cheque distinto, indicá el banco para diferenciarlos."
    )


def get_cheque(db: Session, cheque_id: uuid.UUID) -> Cheque:
    cheque = db.get(Cheque, cheque_id)
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    return cheque


def resolve_cheque(db: Session, nro: str, banco: str | None = None) -> Cheque:
    """Resuelve una referencia a un cheque (número, posiblemente parcial) a una fila.

    El operador suele nombrar el cheque por su número (a veces solo los últimos
    dígitos). Como el número ya NO es único entre bancos, esta función:
      1. Busca por número exacto; si no hay, por sufijo ("el 681" → "…03789681").
      2. Si se indicó banco, filtra por él.
      3. Si queda uno, lo devuelve. Si hay varios, prefiere el que está EN CARTERA
         —el único operable— y recién ahí pide desambiguar por banco.
    """
    nro = (nro or "").strip()
    if not nro:
        raise ValidationError("Indicá el número de cheque.")

    # Orden por antigüedad: con la recompra un mismo número puede tener varias
    # pasadas, y abajo se elige "la última" cuando todas cerraron. Sin ORDER BY,
    # cuál devuelve Postgres es capricho del plan de ejecución.
    orden = Cheque.created_at

    # Los cheques anulados no se resuelven: para el operador dejaron de existir.
    matches = list(
        db.scalars(
            select(Cheque)
            .where(Cheque.nro_cheque == nro, Cheque.anulado_at.is_(None))
            .order_by(orden)
        )
    )
    if not matches:
        matches = list(
            db.scalars(
                select(Cheque)
                .where(Cheque.nro_cheque.endswith(nro), Cheque.anulado_at.is_(None))
                .order_by(orden)
            )
        )
    if not matches:
        # Un e-cheq cargado desde un comprobante de emisión no tiene número, así
        # que no hay forma de que aparezca en esta búsqueda (§0030). Si hay alguno
        # en cartera, mencionarlo evita que el operador crea que se perdió: el
        # cheque está, lo que falta es con qué nombrarlo.
        sin_numero = list(
            db.scalars(
                select(Cheque).where(
                    Cheque.nro_cheque.is_(None),
                    Cheque.anulado_at.is_(None),
                    Cheque.estado == ChequeEstado.EN_CARTERA,
                )
            )
        )
        if sin_numero:
            cuantos = (
                "hay 1 cheque en cartera sin número cargado"
                if len(sin_numero) == 1
                else f"hay {len(sin_numero)} cheques en cartera sin número cargado"
            )
            raise NotFoundError(
                f"No encontré ningún cheque con el número '{nro}'. Ojo: {cuantos} "
                "(e-cheq cargados desde un comprobante que no lo traía). Si es uno "
                "de esos, completale el número desde el panel y volvé a intentar."
            )
        raise NotFoundError(f"No encontré ningún cheque con el número '{nro}'.")

    if banco:
        filtrados = [c for c in matches if c.banco and banco.lower() in c.banco.lower()]
        if filtrados:
            matches = filtrados

    if len(matches) == 1:
        return matches[0]

    # Varias filas con el mismo número: desde la recompra (§0028) el caso normal ya
    # no es "dos bancos distintos" sino **el mismo papel en su segunda vuelta**. Ahí
    # pedir el banco es un callejón —es el mismo banco en las dos—, así que se
    # resuelve por estado, que es lo que de verdad las distingue.
    en_cartera = [c for c in matches if c.estado == ChequeEstado.EN_CARTERA]
    if len(en_cartera) == 1:
        # El único operable: las pasadas cerradas no admiten más movimientos.
        return en_cartera[0]

    if not en_cartera:
        # Ninguno en cartera: todas las pasadas cerraron. El operador se refiere a
        # la última, y devolverla hace que el error sea el útil ("ese cheque ya está
        # VENDIDO") en vez de un pedido de desambiguación que no tiene respuesta.
        return matches[-1]

    # Varios EN CARTERA con el mismo número: son cheques distintos de bancos
    # distintos (el índice único impide dos del mismo papel), así que acá el banco
    # SÍ desambigua.
    detalle = ", ".join(f"{c.nro_cheque} ({c.banco or 'sin banco'})" for c in en_cartera[:5])
    raise ValidationError(
        f"Hay {len(en_cartera)} cheques en cartera con ese número: {detalle}. "
        "Indicá el banco para distinguirlos."
    )


def get_cheque_foto(db: Session, cheque_id: uuid.UUID) -> tuple[bytes, str]:
    """Devuelve (bytes, mime) de la foto del cheque.

    La columna `foto` es diferida: este acceso dispara la carga del binario solo
    para este cheque puntual (no para los listados).
    """
    cheque = db.get(Cheque, cheque_id)
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if cheque.foto is None:
        raise NotFoundError("El cheque no tiene foto.")
    return cheque.foto, cheque.foto_mime or "image/jpeg"


def list_cheques(db: Session, estado: ChequeEstado | None = None) -> list[Cheque]:
    query = select(Cheque).where(Cheque.anulado_at.is_(None))
    if estado is not None:
        query = query.where(Cheque.estado == estado)
    cheques = list(db.scalars(query.order_by(Cheque.created_at.desc())))
    _anotar_vuelta(db, cheques)
    return cheques


def _anotar_vuelta(db: Session, cheques: list[Cheque]) -> None:
    """Le pega a cada cheque el atributo `vuelta`: qué pasada por el negocio es (§Recompra).

    Va en UNA consulta para todo el listado, no una por fila. El filtro por estado
    obliga a computarlo aparte: en la pestaña de cartera se ve la segunda vuelta
    pero no la primera —ya vendida—, así que la posición no se puede deducir de las
    filas que se están mostrando; hay que preguntarle a la tabla entera.

    Casi ningún cheque tiene más de una pasada, así que la consulta trae solo los
    números repetidos y el resto queda en 1 sin costo."""
    if not cheques:
        return
    for cheque in cheques:
        cheque.vuelta = 1

    # Los cheques sin número quedan siempre en vuelta 1: no se los puede agrupar
    # con nada, porque sin número no hay con qué decir que son la misma lámina
    # (§0030). Además un `IN (NULL, …)` no matchearía igual.
    numeros = {c.nro_cheque for c in cheques if c.nro_cheque}
    if not numeros:
        return

    papel = func.coalesce(Cheque.banco, "")
    # Un número puede aparecer entre los repetidos por una recompra o porque son
    # dos láminas distintas de bancos distintos; agrupar por (papel, nro) separa
    # los dos casos, y `nro_cheque` solo acota el universo a lo que estamos viendo.
    repetidos = (
        select(papel.label("papel"), Cheque.nro_cheque)
        .where(
            Cheque.anulado_at.is_(None),
            Cheque.nro_cheque.in_(numeros),
        )
        .group_by(papel, Cheque.nro_cheque)
        .having(func.count() > 1)
        .subquery()
    )
    filas = db.execute(
        select(Cheque.id, papel, Cheque.nro_cheque, Cheque.created_at)
        .join(
            repetidos,
            (papel == repetidos.c.papel) & (Cheque.nro_cheque == repetidos.c.nro_cheque),
        )
        .where(Cheque.anulado_at.is_(None))
        .order_by(Cheque.created_at)
    ).all()

    vueltas: dict[uuid.UUID, int] = {}
    contador: dict[tuple[str, str], int] = {}
    for cheque_id, banco_papel, nro, _creado in filas:
        clave = (banco_papel, nro)
        contador[clave] = contador.get(clave, 0) + 1
        vueltas[cheque_id] = contador[clave]

    for cheque in cheques:
        if (n := vueltas.get(cheque.id)) is not None:
            cheque.vuelta = n


def transition_cheque(
    db: Session,
    cheque_id: uuid.UUID,
    payload: ChequeManualTransition,
    event_at: datetime | None = None,
) -> Cheque:
    if payload.target_state == ChequeEstado.FIADO:
        raise ValidationError(
            "Para fiar un cheque use /cheques/{cheque_id}/fiar, "
            "que crea la deuda asociada en la misma transaccion."
        )

    cheque = db.scalar(
        select(Cheque).where(Cheque.id == cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")

    try:
        cheque.transition_to(
            payload.target_state,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
            cliente_destino_id=payload.cliente_destino_id,
            event_at=event_at,
        )
        # Vender o cobrar el cheque hace entrar plata a la caja ARS.
        #  VENDIDO → lo recibido = monto·(1−%venta);  COBRADO → el nominal completo.
        ingreso: Decimal | None = None
        if payload.target_state == ChequeEstado.VENDIDO:
            ingreso = (cheque.monto * (_CIEN - cheque.porcentaje_venta) / _CIEN).quantize(Decimal("0.01"))
            categoria = CajaCategoria.VENTA_CHEQUE
            accion = "Venta"
        elif payload.target_state == ChequeEstado.COBRADO:
            ingreso = cheque.monto.quantize(Decimal("0.01"))
            categoria = CajaCategoria.COBRO_CHEQUE
            accion = "Cobro"
        if ingreso is not None and ingreso > 0:
            svc_caja.registrar(
                db, fecha=fecha_local(event_at), moneda=Moneda.ARS, tipo=CajaTipo.INGRESO,
                categoria=categoria, monto=ingreso,
                medio_pago=payload.medio_pago,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=f"{accion} {describir(cheque)}",
            )
        db.commit()
        db.refresh(cheque)
        return cheque
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo cambiar el estado del cheque.") from exc


def resync_caja_cheque(db: Session, cheque: Cheque) -> None:
    """Reconstruye el rastro de caja de un cheque desde su estado actual.

    Borra las líneas de caja del cheque y las vuelve a crear: egreso de compra
    siempre; ingreso de venta/cobro según el estado. Se usa tras editar
    monto/%compra/%venta. No hace commit (lo hace el caller).

    Los medios se leen **antes** de barrer: un cheque comprado por transferencia
    y vendido en efectivo tiene cada pata en una caja distinta, y rehacerlas
    todas en efectivo descuadraría las dos (§Caja paralela)."""
    medio_compra = svc_caja.medio_de_referencia(
        db, "cheque", cheque.id, CajaCategoria.COMPRA_CHEQUE
    )
    medio_venta = svc_caja.medio_de_referencia(
        db,
        "cheque",
        cheque.id,
        CajaCategoria.VENTA_CHEQUE
        if cheque.estado == ChequeEstado.VENDIDO
        else CajaCategoria.COBRO_CHEQUE,
    )
    svc_caja.borrar_por_referencia(db, "cheque", cheque.id)
    pagado = (cheque.monto * (_CIEN - cheque.porcentaje_compra) / _CIEN).quantize(Decimal("0.01"))
    # El egreso es por lo que se abonó, no por el valor neto: un cheque comprado a
    # deber solo sacó de la caja lo que se pagó en el acto. Sin esto, cualquier
    # edición posterior (hasta cambiar el banco) le inventaría el egreso entero.
    abonado, _a_deber = svc_pasivos.repartir_compra(pagado, cheque.monto_abonado)
    # La cartera preexistente nunca asentó el egreso de compra: al resincronizar
    # no hay que inventarlo. Sin esto, editar un cheque de carga inicial le haría
    # aparecer un egreso que no existió.
    if abonado > 0 and not cheque.es_carga_inicial:
        # Mismo texto que el alta, que es lo único que un resync debería hacer.
        # Armado a mano, el número que puede faltar salía como "Nº None" y el
        # e-cheq se degradaba a "cheque": editar un cheque **reescribía** su
        # línea ya buena, así que el texto correcto duraba hasta la primera
        # corrección.
        parcial = " (pago parcial)" if abonado < pagado else ""
        svc_caja.registrar(
            db, fecha=fecha_local(cheque.created_at), moneda=Moneda.ARS, tipo=CajaTipo.EGRESO,
            categoria=CajaCategoria.COMPRA_CHEQUE, monto=abonado,
            medio_pago=medio_compra,
            referencia_tipo="cheque", referencia_id=cheque.id,
            detalle=f"Compra {describir(cheque)}{parcial}",
        )
    if cheque.estado == ChequeEstado.VENDIDO and cheque.porcentaje_venta is not None:
        ingreso = (cheque.monto * (_CIEN - cheque.porcentaje_venta) / _CIEN).quantize(Decimal("0.01"))
        if ingreso > 0:
            svc_caja.registrar(
                db, fecha=fecha_local(cheque.ultimo_evento_manual_at), moneda=Moneda.ARS,
                tipo=CajaTipo.INGRESO, categoria=CajaCategoria.VENTA_CHEQUE, monto=ingreso,
                medio_pago=medio_venta,
                referencia_tipo="cheque", referencia_id=cheque.id,
                detalle=f"Venta {describir(cheque)}",
            )
    elif cheque.estado == ChequeEstado.COBRADO:
        svc_caja.registrar(
            db, fecha=fecha_local(cheque.ultimo_evento_manual_at), moneda=Moneda.ARS,
            tipo=CajaTipo.INGRESO, categoria=CajaCategoria.COBRO_CHEQUE,
            monto=cheque.monto.quantize(Decimal("0.01")),
            medio_pago=medio_venta,
            referencia_tipo="cheque", referencia_id=cheque.id,
            detalle=f"Cobro {describir(cheque)}",
        )


def editar_cheque(db: Session, cheque_id: uuid.UUID, payload: ChequeUpdate) -> Cheque:
    """Corrige la carga de un cheque (panel). Aplica reglas de bloqueo por estado.

    - COBRADO/RECHAZADO: terminal, no editable.
    - EN_CARTERA: campos base (nro, banco, monto, %compra, fechas, origen).
    - VENDIDO/FIADO: además %venta y destino; recalcula ganancia, fiado y caja.
    """
    cheque = db.scalar(select(Cheque).where(Cheque.id == cheque_id).with_for_update())
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if cheque.estado in (ChequeEstado.COBRADO, ChequeEstado.RECHAZADO):
        raise ConflictError(
            f"El cheque está {cheque.estado.value} (terminal) y no se puede editar."
        )

    data = payload.model_dump(exclude_unset=True)
    tiene_venta = cheque.estado in (ChequeEstado.VENDIDO, ChequeEstado.FIADO)

    # El monto y el %compra definen cuánto se pagó por el cheque; si quedó a deber,
    # también cuánto se debe. El pasivo puede tener pagos encima o estar compensado
    # contra un cliente, así que se corrige eliminando el cheque y volviéndolo a
    # cargar —que revisa esas dos cosas— en vez de reescribir la deuda por atrás.
    if ("monto" in data or "porcentaje_compra" in data) and svc_pasivos.pasivo_de_origen(
        db, "cheque", cheque.id
    ) is not None:
        raise ConflictError(
            "Este cheque se compró a deber y su deuda ya está cargada: para "
            "corregir el monto o el porcentaje, eliminalo y volvé a cargarlo."
        )

    # Campos solo disponibles tras la venta/fiado.
    for campo in ("porcentaje_venta", "cliente_destino_id"):
        if campo in data and data[campo] is not None and not tiene_venta:
            raise ValidationError(
                f"No se puede fijar '{campo}' en un cheque {cheque.estado.value}: "
                "primero hay que venderlo o fiarlo."
            )

    if "nro_cheque" in data:
        cheque.nro_cheque = data["nro_cheque"].strip()
    if "banco" in data:
        cheque.banco = (data["banco"].strip() or None) if data["banco"] else None
    if "monto" in data:
        cheque.monto = data["monto"]
    if "porcentaje_compra" in data:
        cheque.porcentaje_compra = data["porcentaje_compra"]
    if "fecha_emision" in data:
        cheque.fecha_emision = data["fecha_emision"]
    if "fecha_pago" in data:
        cheque.fecha_pago = data["fecha_pago"]
    if "cliente_origen_id" in data:
        cheque.cliente_origen_id = data["cliente_origen_id"]
    # El tipo es una etiqueta: no entra en ningún cálculo, así que corregir un
    # e-cheq cargado como papel no dispara el resync de caja de más abajo.
    if data.get("tipo") is not None:
        cheque.tipo = data["tipo"]
    if tiene_venta and data.get("porcentaje_venta") is not None:
        cheque.porcentaje_venta = data["porcentaje_venta"]
    if tiene_venta and "cliente_destino_id" in data:
        cheque.cliente_destino_id = data["cliente_destino_id"]

    # Recalcular ganancia (venta) y la deuda del fiado abierto, si aplican.
    if cheque.estado == ChequeEstado.VENDIDO and cheque.porcentaje_venta is not None:
        cheque.ganancia = (
            cheque.monto * (cheque.porcentaje_compra - cheque.porcentaje_venta) / _CIEN
        ).quantize(Decimal("0.01"))
    if (
        cheque.estado == ChequeEstado.FIADO
        and cheque.fiado_originado is not None
        and cheque.fiado_originado.estado == FiadoEstado.ABIERTO
    ):
        fiado = cheque.fiado_originado
        # Solo se recalcula la deuda si el fiado todavía no recibió cobros parciales
        # (saldo == deuda inicial); si ya cobró algo, tocar el monto la desincronizaría.
        deuda_inicial = (
            fiado.monto_original * (_CIEN - fiado.porcentaje_venta) / _CIEN
        ).quantize(Decimal("0.01"))
        if fiado.saldo_pendiente == deuda_inicial:
            if cheque.porcentaje_venta is not None:
                fiado.porcentaje_venta = cheque.porcentaje_venta
            fiado.monto_original = cheque.monto
            fiado.saldo_pendiente = (
                cheque.monto * (_CIEN - fiado.porcentaje_venta) / _CIEN
            ).quantize(Decimal("0.01"))

    try:
        resync_caja_cheque(db, cheque)
        db.commit()
        db.refresh(cheque)
        return cheque
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(_msg_duplicado(db, cheque.nro_cheque, cheque.banco)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo editar el cheque.") from exc


def fiar_cheque(
    db: Session,
    cheque_id: uuid.UUID,
    payload: ChequeFiarRequest,
    fecha_fiado: date | None = None,
    event_at: datetime | None = None,
) -> tuple[Cheque, Fiado]:
    cheque = db.scalar(
        select(Cheque).where(Cheque.id == cheque_id).with_for_update()
    )
    if cheque is None:
        raise NotFoundError("Cheque no encontrado.")
    if db.get(Cliente, payload.cliente_destino_id) is None:
        raise NotFoundError("Cliente destino no encontrado.")

    saldo_pendiente = (
        cheque.monto * (Decimal("100") - payload.porcentaje_venta) / Decimal("100")
    ).quantize(Decimal("0.01"))

    fiado = Fiado(
        cheque_id=cheque.id,
        cliente_id=payload.cliente_destino_id,
        monto_original=cheque.monto,
        porcentaje_venta=payload.porcentaje_venta,
        saldo_pendiente=saldo_pendiente,
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=fecha_fiado or hoy_local(),
    )

    try:
        cheque.transition_to(
            ChequeEstado.FIADO,
            operador_id=payload.operador_id,
            motivo=payload.motivo,
            porcentaje_venta=payload.porcentaje_venta,
            cliente_destino_id=payload.cliente_destino_id,
            event_at=event_at,
        )
        db.add(fiado)
        db.commit()
        db.refresh(cheque)
        db.refresh(fiado)
        return cheque, fiado
    except (InvalidChequeStateTransition, ManualOperationRequired) as exc:
        db.rollback()
        raise ValidationError(str(exc)) from exc
    except SQLAlchemyError as exc:
        db.rollback()
        raise DatabaseWriteError("No se pudo fiar el cheque.") from exc
