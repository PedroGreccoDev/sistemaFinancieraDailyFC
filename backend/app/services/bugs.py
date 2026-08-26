"""Registro de bugs: cada error del sistema con su numeral.

Resuelve un problema concreto: hasta acá el aviso llegaba **cuando el operador
ya no podía trabajar**. Un error del panel moría en los logs de Railway, y los
veinte `except Exception` que loguean y siguen no le avisaban a nadie — el
descuadre se descubría al cerrar el día.

Desde acá cualquier error, se haya tragado o no, entra en la tabla `bugs`, sale
con un número, y ese número llega a Telegram en el momento.

Tres decisiones que conviene no deshacer:

1. **A Telegram va el numeral, nunca el traceback.** El mensaje de una
   excepción de SQLAlchemy arrastra el SQL con montos, nombres de clientes y
   teléfonos, y Telegram es un tercero (la misma decisión que ya tomaba
   `webhook._ubicacion`). El detalle completo queda en la tabla, que es de
   casa, y se lee en `docs/BUGS.md`.

2. **Capturar nunca bloquea ni lanza.** `capturar()` solo encola; una tarea de
   fondo escribe en Postgres y avisa. Si registrar un error costara una
   escritura sincrónica, un pico de errores frenaría el event loop justo cuando
   el sistema ya está en problemas — y una falla al anotar el bug volteando la
   operación que lo produjo sería peor que no tener registro.

3. **El antiflood vive en la fila, no en memoria.** Railway reinicia el proceso
   seguido; un contador en RAM haría que cada redeploy volviera a avisar de lo
   mismo desde cero.

Ver §Registro de bugs.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import threading
import traceback
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.db.models import Bug
from app.db.session import SessionLocal
from app.services import telegram
from app.services.exceptions import ServiceError

logger = logging.getLogger(__name__)


# Orígenes válidos. Es de dónde vino el error, no de qué se trata.
ORIGEN_BOT      = "bot"
ORIGEN_PANEL    = "panel"
ORIGEN_FRONTEND = "frontend"
ORIGEN_TESTING  = "testing"
ORIGEN_MONITOR  = "monitor"

# Marca que se le cuelga a la instancia de excepción ya capturada. Una misma
# excepción pasa por varias manos —el `logger.exception` del servicio y después
# el handler global de FastAPI— y sin esto sumaría dos ocurrencias por un solo
# error, inflando el contador que justamente sirve para medir gravedad.
_MARCA = "_bug_capturado"

# Anti-recursión: si escribir un bug falla y eso loguea un error, el handler de
# logs lo capturaría y volvería a entrar acá para siempre.
_local = threading.local()

_tarea: asyncio.Task | None = None

# Fragmentos de ruta que son datos y no camino: UUIDs y enteros largos. Sin
# esto `/clientes/{uuid}` abriría un bug distinto por cada cliente.
_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_NUM = re.compile(r"\b\d{2,}\b")


@dataclass
class Evento:
    """Un error detectado, todavía sin número: el número lo da la base."""

    origen:      str
    titulo:      str
    tipo:        str
    ubicacion:   str
    ambito:      str = ""
    detalle:     str = ""
    contexto:    dict[str, Any] | None = None
    sesion_test: str | None = None
    huella:      str = field(default="", init=False)

    def __post_init__(self) -> None:
        self.huella = calcular_huella(self.tipo, self.ubicacion, self.ambito)


@dataclass
class Registrado:
    """Lo que quedó en la base, con el numeral ya asignado."""

    id:            int
    ocurrencias:   int
    nuevo:         bool
    reabierto:     bool
    ultimo_aviso:  datetime | None = None


# Cola en memoria entre quien detecta el error y quien lo escribe. Acotada a
# propósito: si el drenador se traba, un error en loop no puede comerse la RAM
# del proceso. Se pierden los más viejos, que a esa altura ya están contados.
_COLA: deque[Evento] = deque(maxlen=500)


# ══════════════════════════════════════════════════════════════════════
#  Huella e identificación
# ══════════════════════════════════════════════════════════════════════

def calcular_huella(tipo: str, ubicacion: str, ambito: str) -> str:
    """Identidad estable de un bug: qué se rompió, dónde y por qué camino.

    Sobre los valores: quedan afuera a propósito. Si el monto o el nombre del
    cliente entraran, el mismo error con otro cliente sería un bug nuevo y el
    contador no mediría nada.
    """
    crudo = f"{tipo}|{ubicacion}|{normalizar_ambito(ambito)}"
    return hashlib.sha1(crudo.encode("utf-8")).hexdigest()[:32]


def normalizar_ambito(ambito: str) -> str:
    """Saca los identificadores de la ruta: `/clientes/3f2a…` → `/clientes/{id}`."""
    sin_uuid = _UUID.sub("{id}", ambito or "")
    return _NUM.sub("{id}", sin_uuid)


def ubicacion_de(exc: BaseException) -> str:
    """`archivo.py:línea` del último frame propio de la excepción.

    Busca el último frame que esté dentro de `app/`: el último frame a secas
    suele caer adentro de SQLAlchemy o de httpx, que es cierto pero inútil —
    todos los errores de base darían la misma línea de la librería y se
    juntarían en un solo bug inservible.
    """
    tb = exc.__traceback__
    if tb is None:
        return "ubicación desconocida"

    frames = traceback.extract_tb(tb)
    if not frames:
        return "ubicación desconocida"

    propios = [f for f in frames if "app" in Path(f.filename).parts]
    elegido = propios[-1] if propios else frames[-1]
    return f"{Path(elegido.filename).name}:{elegido.lineno}"


def _traceback_completo(exc: BaseException) -> str:
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def es_error_de_negocio(exc: BaseException) -> bool:
    """Si es un error esperado que no merece bug.

    Un `ServiceError` es el sistema diciendo que no: "el cliente no existe", "el
    cheque ya está vendido". Son la operación normal del negocio y entrarían de
    a cientos por día, tapando lo que sí importa.

    La excepción es `DatabaseWriteError` y cualquier otro `ServiceError` de 5xx:
    esos no son el negocio diciendo que no, son el sistema fallando.
    """
    return isinstance(exc, ServiceError) and exc.status_code < 500


# ══════════════════════════════════════════════════════════════════════
#  Captura (nunca bloquea, nunca lanza)
# ══════════════════════════════════════════════════════════════════════

def capturar(
    exc: BaseException,
    *,
    origen: str,
    ambito: str = "",
    titulo: str | None = None,
    contexto: dict[str, Any] | None = None,
    sesion_test: str | None = None,
) -> None:
    """Anota una excepción como bug. No bloquea, no lanza, no devuelve nada.

    El numeral se conoce recién cuando la fila se escribe; quien captura no lo
    necesita —lo necesita quien lee Telegram— y esperarlo obligaría a que todo
    punto de captura fuera async y aguantara una escritura a Postgres.
    """
    try:
        if getattr(_local, "dentro", False):
            return
        if es_error_de_negocio(exc):
            return
        if getattr(exc, _MARCA, False):
            return
        try:
            setattr(exc, _MARCA, True)
        except AttributeError:
            pass  # algunas excepciones con __slots__ no lo aceptan; sigue igual

        tipo = type(exc).__name__
        ubicacion = ubicacion_de(exc)
        _encolar(
            Evento(
                origen=origen,
                # El título va a Telegram: se arma con el tipo y el camino, nunca
                # con el mensaje de la excepción, que puede traer datos del negocio.
                titulo=titulo or f"{tipo} en {ambito or ubicacion}",
                tipo=tipo,
                ubicacion=ubicacion,
                ambito=ambito,
                detalle=_traceback_completo(exc),
                contexto=contexto,
                sesion_test=sesion_test,
            )
        )
    except Exception:  # noqa: BLE001 — anotar un bug jamás puede tumbar la operación
        pass


def capturar_mensaje(
    *,
    origen: str,
    titulo: str,
    ubicacion: str,
    tipo: str = "Error",
    ambito: str = "",
    detalle: str = "",
    contexto: dict[str, Any] | None = None,
    sesion_test: str | None = None,
) -> None:
    """Anota un bug que no viene de una excepción.

    Es el caso de los invariantes de negocio: la caja no cuadra, el saldo del
    cliente no coincide con sus movimientos. Nada explotó y sin embargo hay un
    error —el más peligroso, porque no da señal— y merece número igual.
    """
    try:
        if getattr(_local, "dentro", False):
            return
        _encolar(
            Evento(
                origen=origen,
                titulo=titulo,
                tipo=tipo,
                ubicacion=ubicacion,
                ambito=ambito,
                detalle=detalle,
                contexto=contexto,
                sesion_test=sesion_test,
            )
        )
    except Exception:  # noqa: BLE001
        pass


def _encolar(evento: Evento) -> None:
    if not get_settings().bugs_activo:
        return
    _COLA.append(evento)


def pendientes() -> int:
    """Cuántos eventos esperan ser escritos. Para tests y diagnóstico."""
    return len(_COLA)


# ══════════════════════════════════════════════════════════════════════
#  Persistencia
# ══════════════════════════════════════════════════════════════════════

def _persistir(evento: Evento) -> Registrado | None:
    """Escribe el evento y devuelve su numeral. Sesión propia, siempre.

    La sesión es nueva y no la del request a propósito: si el error fue de base,
    la sesión que venía en curso quedó en estado inválido y cualquier cosa que
    se intente sobre ella vuelve a explotar. Anotar el bug tiene que funcionar
    justo cuando lo de al lado se rompió.

    **Busca primero y recién inserta si no está**, en vez de resolver todo con
    un `INSERT … ON CONFLICT`, que es más corto y sale mal por dos motivos:

    1. El `serial` **consume un número igual cuando el insert termina en
       update**. Con un bug que ocurre mil veces, el próximo bug nuevo no sería
       el #13 sino el #1013, y un numeral que salta de a miles deja de servir
       para lo único que existe: decir "el bug 47" y que alguien lo encuentre.
    2. El `RETURNING` de un `ON CONFLICT` devuelve la fila **ya actualizada**,
       así que no hay forma de saber si el bug venía cerrado — y "este bug
       reapareció" es de las pocas cosas que siempre valen un aviso.

    La carrera que abre (dos procesos con el mismo bug nuevo a la vez) la cierra
    el índice único: el segundo choca, relee y actualiza.
    """
    tabla = Bug.__table__
    db = SessionLocal()
    try:
        previo = db.execute(
            sa.select(
                tabla.c.id, tabla.c.ocurrencias, tabla.c.estado, tabla.c.ultimo_aviso_at
            ).where(tabla.c.huella == evento.huella)
        ).one_or_none()

        if previo is None:
            try:
                nuevo_id = db.execute(
                    sa.insert(tabla)
                    .values(
                        huella=evento.huella,
                        origen=evento.origen,
                        titulo=evento.titulo[:200],
                        tipo=evento.tipo[:120],
                        ubicacion=evento.ubicacion[:200],
                        ambito=normalizar_ambito(evento.ambito)[:200],
                        detalle=evento.detalle,
                        contexto=evento.contexto,
                        sesion_test=evento.sesion_test,
                        ocurrencias=1,
                        estado="ABIERTO",
                    )
                    .returning(tabla.c.id)
                ).scalar_one()
                db.commit()
                return Registrado(id=nuevo_id, ocurrencias=1, nuevo=True, reabierto=False)
            except IntegrityError:
                # Otro proceso lo dio de alta en el medio: no es un bug nuevo.
                db.rollback()
                previo = db.execute(
                    sa.select(
                        tabla.c.id, tabla.c.ocurrencias, tabla.c.estado, tabla.c.ultimo_aviso_at
                    ).where(tabla.c.huella == evento.huella)
                ).one()

        # El contador se incrementa en SQL y no en Python: dos ocurrencias
        # simultáneas del mismo bug tienen que sumar dos, no una.
        ocurrencias = db.execute(
            sa.update(tabla)
            .where(tabla.c.id == previo.id)
            .values(
                ocurrencias=tabla.c.ocurrencias + 1,
                ultima_vez=sa.func.now(),
                # Se guarda el traceback más reciente: si el bug mutó, el viejo
                # ya no describe lo que está pasando ahora.
                detalle=evento.detalle,
                contexto=evento.contexto,
                # Un bug cerrado que vuelve a ocurrir no está cerrado.
                estado="ABIERTO" if previo.estado == "CERRADO" else previo.estado,
            )
            .returning(tabla.c.ocurrencias)
        ).scalar_one()
        db.commit()

        return Registrado(
            id=previo.id,
            ocurrencias=ocurrencias,
            nuevo=False,
            reabierto=previo.estado == "CERRADO",
            ultimo_aviso=previo.ultimo_aviso_at,
        )
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        # Sin `logger.error`: el handler de logs lo tomaría como un bug nuevo y
        # entraría en loop. El anti-recursión ya protege, pero esto lo hace obvio.
        logger.warning("No se pudo registrar el bug (%s): %s", evento.titulo, exc)
        return None
    finally:
        db.close()


def _marcar_avisado(bug_id: int) -> None:
    db = SessionLocal()
    try:
        db.execute(
            sa.update(Bug.__table__)
            .where(Bug.__table__.c.id == bug_id)
            .values(
                ultimo_aviso_at=sa.func.now(),
                avisos_enviados=Bug.__table__.c.avisos_enviados + 1,
            )
        )
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("No se pudo marcar el aviso del bug #%s: %s", bug_id, exc)
    finally:
        db.close()


# ══════════════════════════════════════════════════════════════════════
#  Aviso por Telegram
# ══════════════════════════════════════════════════════════════════════

def _escalones() -> set[int]:
    salida = {
        int(parte.strip())
        for parte in get_settings().bugs_escalones.split(",")
        if parte.strip().isdigit()
    }
    return salida or {1}


def _hay_que_avisar(reg: Registrado, ultimo_aviso: datetime | None) -> bool:
    """Cuándo un bug merece interrumpir al dueño.

    La regla vieja era silenciar quince minutos y listo, y tenía un agujero: un
    bug que se dispara de 3 a 3000 ocurrencias no volvía a avisar, justo el caso
    más grave. Acá se avisa **cuando escala** —en los escalones configurados— y
    además cada tantas horas mientras siga vivo.
    """
    if reg.nuevo or reg.reabierto:
        return True
    if reg.ocurrencias in _escalones():
        return True
    if ultimo_aviso is None:
        return True

    horas = max(1, get_settings().bugs_repetir_horas)
    return datetime.now(timezone.utc) - ultimo_aviso >= timedelta(hours=horas)


def texto_aviso(evento: Evento, reg: Registrado) -> str:
    """El mensaje que va a Telegram: el número y dónde, nunca el traceback."""
    from app.services import health

    if reg.reabierto:
        encabezado = f"🔁 <b>Bug #{reg.id} reapareció</b>"
    elif reg.nuevo:
        encabezado = f"🐛 <b>Bug #{reg.id} — nuevo</b>"
    else:
        encabezado = f"🐛 <b>Bug #{reg.id}</b> — va {reg.ocurrencias} veces"

    lineas = [encabezado, ""]
    if evento.ambito:
        lineas.append(f"<code>{telegram.escapar(normalizar_ambito(evento.ambito))}</code>")
    lineas.append(f"{telegram.escapar(evento.tipo)} en {telegram.escapar(evento.ubicacion)}")
    lineas.append(f"origen: {telegram.escapar(evento.origen)}")
    lineas.append("")
    lineas.append(f"🕒 {health.hora_ar(datetime.now(timezone.utc))}")
    return "\n".join(lineas)


async def _avisar(evento: Evento, reg: Registrado) -> None:
    settings = get_settings()
    if not settings.bugs_avisar_telegram or not telegram.configurado():
        return
    if not _hay_que_avisar(reg, reg.ultimo_aviso):
        return

    if await telegram.enviar_alerta(texto_aviso(evento, reg)):
        await asyncio.to_thread(_marcar_avisado, reg.id)


# ══════════════════════════════════════════════════════════════════════
#  Drenador
# ══════════════════════════════════════════════════════════════════════

async def _procesar(evento: Evento) -> Registrado | None:
    reg = await asyncio.to_thread(_persistir, evento)
    if reg is None:
        # La base no aceptó el bug (puede estar caída, que es justo cuando más
        # errores hay). El aviso sale igual, sin número: mejor sin numeral que
        # sin aviso.
        if get_settings().bugs_avisar_telegram and telegram.configurado():
            await telegram.enviar_alerta(
                "🐛 <b>Error sin registrar</b>\n\n"
                f"{telegram.escapar(evento.tipo)} en {telegram.escapar(evento.ubicacion)}\n"
                f"origen: {telegram.escapar(evento.origen)}\n"
                "<i>No se pudo escribir en la tabla de bugs.</i>"
            )
        return None

    await _avisar(evento, reg)
    return reg


async def _ciclo() -> None:
    """Drena la cola. Igual que el monitor de salud: no se muere nunca."""
    intervalo = max(1, get_settings().bugs_intervalo_segundos)
    while True:
        try:
            while _COLA:
                evento = _COLA.popleft()
                _local.dentro = True
                try:
                    await _procesar(evento)
                finally:
                    _local.dentro = False
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            _local.dentro = False
            logger.warning("El drenador de bugs falló en un ciclo: %s", exc)

        await asyncio.sleep(intervalo)


def iniciar() -> None:
    """Arranca el drenador (idempotente). Se llama en el `startup`."""
    global _tarea
    if not get_settings().bugs_activo:
        logger.info("Registro de bugs desactivado (BUGS_ACTIVO=false)")
        return
    if _tarea is not None and not _tarea.done():
        return

    _tarea = asyncio.create_task(_ciclo(), name="drenador-bugs")
    logger.info("Registro de bugs iniciado")


async def detener() -> None:
    """Cancela el drenador, dando una última pasada a lo que quedó encolado."""
    global _tarea
    if _tarea is None:
        return
    try:
        while _COLA:
            await _procesar(_COLA.popleft())
    except Exception:  # noqa: BLE001
        pass

    _tarea.cancel()
    try:
        await _tarea
    except (asyncio.CancelledError, Exception):  # noqa: BLE001
        pass
    _tarea = None


def drenar_sync() -> list[Registrado]:
    """Escribe lo encolado sin event loop y sin avisar por Telegram.

    Es para la sesión de testing y para los tests: ahí no hay tarea de fondo que
    drene, y mil bugs de una corrida no tienen por qué llegar al chat de nadie
    (la sesión manda un único resumen al final).
    """
    salida = []
    while _COLA:
        evento = _COLA.popleft()
        _local.dentro = True
        try:
            reg = _persistir(evento)
        finally:
            _local.dentro = False
        if reg is not None:
            salida.append(reg)
    return salida


# ══════════════════════════════════════════════════════════════════════
#  Captura de logs: los errores que hoy se tragan
# ══════════════════════════════════════════════════════════════════════

class HandlerDeLogs(logging.Handler):
    """Convierte en bug todo `logger.error` / `logger.exception` del proceso.

    Es la pieza que cierra el agujero de fondo. Hay veinte `except Exception`
    que loguean y siguen —a propósito: el bot no puede morirse porque falló un
    envío— y cada uno de esos es un error que nadie ve hasta que algo no cierra.
    Engancharlos uno por uno sería veinte cambios y el veintiuno se olvidaría;
    escuchando el logging entran todos, incluidos los que se escriban mañana.

    Arranca solo en ERROR y CRITICAL. Los WARNING del sistema son ruido operativo
    normal (un cliente ambiguo, un reintento) y llenarían el chat.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            if getattr(_local, "dentro", False):
                return
            # Los módulos que avisan no pueden avisar sobre sí mismos.
            if record.name.startswith(("app.services.bugs", "app.services.telegram")):
                return

            del_bot = "whatsapp" in record.name or "webhook" in record.name
            origen = ORIGEN_BOT if del_bot else ORIGEN_PANEL

            exc = record.exc_info[1] if record.exc_info else None
            if exc is not None:
                capturar(exc, origen=origen, ambito=f"log:{record.name}")
                return

            # Un `logger.error` sin excepción: el mensaje formateado puede traer
            # datos del negocio, así que va al detalle (nuestra base) y el título
            # —que sí viaja a Telegram— se arma con el módulo y la línea.
            capturar_mensaje(
                origen=origen,
                titulo=f"Error logueado en {record.module}",
                tipo="LogError",
                ubicacion=f"{Path(record.pathname).name}:{record.lineno}",
                ambito=f"log:{record.name}",
                detalle=record.getMessage(),
            )
        except Exception:  # noqa: BLE001 — un handler de logs no puede lanzar
            pass


_handler: HandlerDeLogs | None = None


def instalar_captura_de_logs() -> None:
    """Engancha el handler al logger raíz (idempotente)."""
    global _handler
    if not get_settings().bugs_capturar_logs:
        logger.info("Captura de logs como bugs desactivada (BUGS_CAPTURAR_LOGS=false)")
        return
    if _handler is not None:
        return

    _handler = HandlerDeLogs()
    logging.getLogger().addHandler(_handler)
    logger.info("Captura de logs como bugs instalada (nivel ERROR)")


def desinstalar_captura_de_logs() -> None:
    """Saca el handler. Para los tests, que no quieren capturarse entre sí."""
    global _handler
    if _handler is None:
        return
    logging.getLogger().removeHandler(_handler)
    _handler = None
