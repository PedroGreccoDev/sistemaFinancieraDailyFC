"""El freno: que la sesión de carga no escriba jamás en producción.

Es la pieza más importante del paquete y la que menos hace. La sesión da de alta
cheques falsos, cobra deudas inventadas y **borra la base entre bloques**: contra
Railway sería la peor cosa que este repositorio puede hacer.

El riesgo no es hipotético: el `.env` del repo apunta a producción, así que
correr cualquier cosa desde `backend/` **sin setear `DATABASE_URL` a mano ya
lee la base real**. Olvidarse de exportar una variable es lo más fácil del
mundo, y sin este freno el olvido no da ninguna señal hasta que es tarde.

Por eso el criterio es al revés de lo natural: no se buscan señales de
producción para bloquear, se **exige** la prueba de que es local. Una base
desconocida se rechaza. Lo peor que puede pasar así es que alguien tenga que
agregar su host a la lista; al revés, lo peor es irreversible.

Ver §Sesión de carga.
"""

from __future__ import annotations

from urllib.parse import urlparse

# Los únicos hosts donde se puede escribir. Es una lista blanca a propósito:
# cualquier cosa que no esté acá se rechaza sin preguntar.
HOSTS_LOCALES = frozenset({"localhost", "127.0.0.1", "::1", "[::1]", ""})

# Nombres de base que nunca son de prueba, aunque el host engañe (un túnel SSH a
# producción publica Railway en 127.0.0.1 y pasaría el chequeo de host).
NOMBRES_PROHIBIDOS = ("railway", "production", "produccion", "prod")


class DestinoProhibido(RuntimeError):
    """La base configurada no es local. La sesión no arranca."""


def _host_de(url: str) -> str:
    # SQLAlchemy usa `postgresql+psycopg://`, que urlparse entiende igual.
    return (urlparse(url).hostname or "").lower()


def _base_de(url: str) -> str:
    return urlparse(url).path.lstrip("/").lower()


def verificar_destino(database_url: str) -> None:
    """Lanza `DestinoProhibido` si la URL no es una base local de prueba.

    Función pura: se le pasa la URL y no lee el entorno, así se puede testear
    contra la URL de producción sin tenerla configurada.
    """
    if not database_url:
        raise DestinoProhibido(
            "No hay DATABASE_URL. La sesión de carga necesita una base local "
            "explícita; sin ella el proyecto cae en la del .env, que es producción."
        )

    host = _host_de(database_url)
    if host not in HOSTS_LOCALES:
        raise DestinoProhibido(
            f"DATABASE_URL apunta a «{host}», que no es local. La sesión de carga "
            f"escribe y borra datos: solo corre contra {sorted(HOSTS_LOCALES - {''})}.\n"
            "Levantá una base de prueba y exportá DATABASE_URL apuntando ahí."
        )

    base = _base_de(database_url)
    for prohibido in NOMBRES_PROHIBIDOS:
        if prohibido in base:
            raise DestinoProhibido(
                f"La base se llama «{base}» y el nombre tiene «{prohibido}». "
                "El host da local, pero un túnel a producción también da local: "
                "renombrá la base de prueba o usá otra."
            )


def verificar_entorno(database_url: str, telegram_token: str) -> list[str]:
    """Chequeos que no frenan la sesión pero conviene decir en voz alta.

    Devuelve advertencias. La única que frena es la de arriba: acá van las cosas
    que hacen ruido pero no rompen nada, como que el chat de Telegram se llene
    con los cientos de errores que la sesión va a provocar a propósito.
    """
    avisos = []
    if telegram_token:
        avisos.append(
            "TELEGRAM_BOT_TOKEN está seteado: la sesión NO manda los bugs uno por "
            "uno (los escribe con `drenar_sync`), pero conviene vaciarlo igual "
            "para que ningún otro camino avise."
        )
    if _base_de(database_url) in ("postgres", "template1"):
        avisos.append(
            "La base es la de sistema de PostgreSQL. Anda, pero conviene una "
            "propia: la sesión la deja llena de datos inventados."
        )
    return avisos
