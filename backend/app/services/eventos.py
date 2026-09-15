"""eventos.py — Registrar lo que pasó cuando no queda rastro en ninguna tabla.

Movimientos es el diario del negocio: **toda operación deja renglón, mueva plata
o no** _(decisión del dueño, 2026-09-14)_. Casi todo se deriva —el libro de
caja, los cheques, los fiados, las compensaciones, los pasivos— y para eso no
hace falta guardar nada. Lo que se registra acá son las operaciones que **no
dejan fila en ninguna parte**: el cobro con cheque, la anulación y la
corrección (§Historial unificado).

**La regla de oro es no duplicar.** Si el hecho ya se ve por el libro de caja o
por su propia tabla, no se registra un evento: Movimientos lo mostraría dos
veces y el operador tendría que adivinar cuál de los dos renglones es el real.

`anotar` **no commitea**, igual que `svc_caja.registrar`: el evento es parte
de la misma transacción que la operación que lo genera. Un evento commiteado
aparte contaría algo que después pudo no pasar.
"""

from __future__ import annotations

import enum
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy.orm import Session

from app.core.fechas import hoy_local
from app.db.models import Evento, Moneda


def anotar(
    db: Session,
    *,
    categoria: str,
    grupo: str,
    descripcion: str,
    fecha: date | None = None,
    monto: Decimal | None = None,
    moneda: Moneda | None = None,
    referencia_tipo: str | None = None,
    referencia_id: uuid.UUID | None = None,
    operador: str | None = None,
) -> Evento:
    """Anota un evento del diario. Sin commit: lo hace el caller.

    Se llama `anotar` y no `registrar` **a propósito**: `registrar` es la caja, y
    el guardián que exige `medio_pago` en toda llamada a `caja.registrar` mira el
    nombre (`test_caja_paralela`). Un evento no tiene medio de pago —no pasó por
    ninguna caja—, así que compartir el nombre lo hacía saltar.
    """
    evento = Evento(
        fecha=fecha or hoy_local(),
        categoria=categoria,
        grupo=grupo,
        descripcion=descripcion.strip(),
        monto=monto,
        moneda=moneda,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        operador=(operador or "").strip() or None,
    )
    db.add(evento)
    return evento


def anulacion(
    db: Session,
    *,
    descripcion: str,
    motivo: str,
    operador: str,
    referencia_tipo: str,
    referencia_id: uuid.UUID,
    monto: Decimal | None = None,
    moneda: Moneda | None = None,
) -> Evento:
    """Deshacer algo es una operación del día, y de las importantes.

    La anulación borra las líneas de caja y marca la fila como anulada: el
    renglón original **desaparece** del día y sin esto nadie se entera de que
    existió. El motivo va en el texto porque es la mitad de la información —qué
    se deshizo y por qué—, y es lo primero que se pregunta después.
    """
    return anotar(
        db,
        categoria="ANULACION",
        grupo="ANULACIONES",
        descripcion=f"Anulado: {descripcion} · motivo: {motivo.strip()}",
        monto=monto,
        moneda=moneda,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        operador=operador,
    )


def foto(obj, etiquetas: dict[str, str]) -> dict[str, object]:
    """Copia los campos que se van a comparar, **antes** de tocarlos.

    Hay que llamarla antes de aplicar la edición: después de aplicarla el valor
    viejo ya no está en ningún lado, y ese es justamente el dato que falta para
    contar qué cambió.
    """
    return {campo: getattr(obj, campo, None) for campo in etiquetas}


def _valor(v: object) -> str:
    """Un valor como lo lee el operador, no como lo guarda la base."""
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "sí" if v else "no"
    if isinstance(v, Decimal):
        return f"{v:,.2f}"
    if isinstance(v, date):
        return v.strftime("%d/%m/%Y")
    if isinstance(v, enum.Enum):
        return str(v.value)
    return str(v)


def cambios(antes: dict[str, object], obj, etiquetas: dict[str, str]) -> list[str]:
    """Qué cambió de verdad, campo por campo: `"monto: 10.000,00 → 12.000,00"`.

    Compara la foto contra el objeto ya editado. Solo lo que cambió: mandar el
    payload entero llenaría el diario de campos que se reenviaron iguales, que
    es lo que hace el panel cada vez que se abre y se guarda un formulario.
    """
    salida: list[str] = []
    for campo, etiqueta in etiquetas.items():
        viejo = antes.get(campo)
        nuevo = getattr(obj, campo, None)
        if viejo != nuevo:
            salida.append(f"{etiqueta}: {_valor(viejo)} → {_valor(nuevo)}")
    return salida


def correccion(
    db: Session,
    *,
    que: str,
    cambios: list[str],
    referencia_tipo: str,
    referencia_id: uuid.UUID,
    operador: str | None = None,
) -> Evento | None:
    """Corregir una carga cambia el número del día y no dejaba rastro.

    `cambios` son los campos que efectivamente cambiaron, ya redactados por el
    servicio que los aplicó (`"monto: $10.000 → $12.000"`). **Si no cambió
    nada, no se registra evento**: guardar "se editó" sin diferencia llenaría el
    diario de renglones que no cuentan nada.
    """
    if not cambios:
        return None
    return anotar(
        db,
        categoria="CORRECCION",
        grupo="CORRECCIONES",
        descripcion=f"Corregido: {que} · " + " · ".join(cambios),
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
        operador=operador,
    )


def nombrar_cheques(cheques) -> str:
    """Cómo se nombra en una frase el papel (o los papeles) que entregó el cliente.

    Con uno solo se lo nombra entero; con varios, cuántos son y sus números —la
    lista completa de bancos y montos no entra en un renglón y el operador los
    reconoce por el número—.
    """
    # Import local: `cheques` importa `pasivos`, que importa este módulo.
    from app.services.cheques import describir

    if not cheques:
        return "cheques"
    if len(cheques) == 1:
        return describir(cheques[0], con_monto=False)
    numeros = ", ".join(
        f"Nº {c.nro_cheque}" if c.nro_cheque else "sin número" for c in cheques
    )
    return f"{len(cheques)} cheques ({numeros})"


def cobro_con_cheque(
    db: Session,
    *,
    cliente: str,
    concepto: str,
    cheques,
    imputado: Decimal,
    moneda: Moneda,
    fecha: date | None = None,
    referencia_tipo: str | None = None,
    referencia_id: uuid.UUID | None = None,
) -> Evento:
    """El cliente pagó con papeles: bajan saldos y la caja no se mueve.

    De esta operación **no quedaba nada**: el cheque entra a cartera por su lado
    —y eso sí se ve— pero que haya saldado una deuda, de quién y por cuánto, no
    vivía en ninguna tabla. En Movimientos se veía entrar un papel y nada más.

    El monto del renglón es **lo que bajó la deuda**, no el nominal del cheque:
    son dos números distintos (el papel se toma con descuento) y el que cuenta
    como cobro es el primero. El nominal ya se ve en la línea del cheque que
    entró a cartera.
    """
    return anotar(
        db,
        categoria="COBRO_CHEQUE_DEUDA",
        grupo="COBROS",
        descripcion=f"{cliente} pagó {concepto} con {nombrar_cheques(cheques)}",
        fecha=fecha,
        monto=imputado,
        moneda=moneda,
        referencia_tipo=referencia_tipo,
        referencia_id=referencia_id,
    )
