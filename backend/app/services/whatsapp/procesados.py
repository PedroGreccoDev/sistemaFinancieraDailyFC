"""Los mensajes que el bot ya atendió, para no atenderlos dos veces.

WAHA **reintenta** un webhook que no le contesta a tiempo, y una config con el
webhook cargado por duplicado entrega cada mensaje dos veces (pasó el
2026-08-27: el mismo webhook en la env var global y en la config de la sesión).
El webhook del bot no tenía cómo notarlo —dos entregas del mismo mensaje son
indistinguibles de dos pedidos idénticos— así que **cargaba la operación dos
veces**: no era una respuesta repetida, era plata cargada dos veces.

Cada mensaje de WhatsApp trae su `id` y el parser ya lo venía extrayendo sin que
nadie lo usara. Acá se anota el de cada mensaje atendido y se descarta el que
vuelve.

**Un `message_id` vacío se deja pasar SIEMPRE.** Es el modo de falla que hay que
cuidar: si un día WAHA dejara de mandar el id, tratar el string vacío como "ya
visto" haría que el bot ignore todos los mensajes menos el primero — quedaría
mudo por una defensa contra duplicados. Perder la protección es aceptable;
perder el bot no.

Vive en memoria del proceso, igual que la sesión conversacional y el estado del
monitor: el reintento de WAHA llega en segundos, así que un redeploy que vacíe
esto no abre ninguna ventana real. Asume **un solo worker de uvicorn** (lo que
hace `entrypoint.sh`); con varios, cada uno llevaría su propia lista y un
duplicado repartido entre dos workers pasaría igual.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

# Ventana en la que un mensaje repetido se considera el mismo. Los reintentos
# de WAHA son de segundos; una hora es holgura de sobra sin acumular nada.
_TTL_MINUTES = 60

# Tope duro de ids recordados. Es una red contra un flujo anormal de mensajes
# —no puede crecer sin límite— y no una capacidad de trabajo: con el TTL de
# arriba, la operación normal del día ni se acerca.
_MAX_IDS = 2_000

_vistos: dict[str, datetime] = {}


def ya_procesado(message_id: str) -> bool:
    """Anota el mensaje y dice si ya había pasado por acá.

    El chequeo y la anotación son **un solo paso, sin `await` en el medio**, y
    eso es lo que hace que dos entregas simultáneas del mismo mensaje no se
    crucen: el event loop no puede cortar entre mirar y anotar. Partirlo en un
    `if ya_visto(...)` + `marcar(...)` reabriría exactamente el caso que esto
    viene a cerrar, porque las dos entregas duplicadas llegan con milisegundos
    de diferencia.

    Returns:
        True si el mensaje ya se había atendido (hay que descartarlo).
    """
    if not message_id:
        return False  # sin id no se puede deduplicar; ver el docstring del módulo

    if message_id in _vistos:
        return True

    _vistos[message_id] = datetime.now(UTC)
    # La purga va DESPUÉS de anotar, o el tope se pasa por uno: recortar a
    # `_MAX_IDS` y recién entonces insertar deja el registro en `_MAX_IDS + 1`.
    _purgar()
    return False


def olvidar_todo() -> None:
    """Vacía el registro. Existe para los tests."""
    _vistos.clear()


# ── Helpers privados ─────────────────────────────────────────────────────────

def _purgar() -> None:
    corte = datetime.now(UTC) - timedelta(minutes=_TTL_MINUTES)
    for mid in [m for m, visto in _vistos.items() if visto < corte]:
        del _vistos[mid]

    # Si aun así hay de más, se van los más viejos primero: un dict conserva el
    # orden de inserción, que acá es el orden en que llegaron los mensajes.
    sobran = len(_vistos) - _MAX_IDS
    for mid in list(_vistos)[:sobran] if sobran > 0 else []:
        del _vistos[mid]
