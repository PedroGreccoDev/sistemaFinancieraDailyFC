"""El freno de la sesión de carga: que no escriba jamás en producción.

Es el test más importante de la sesión de carga y el que cubre lo más barato de
romper. La sesión da de alta operaciones falsas y borra datos entre bloques:
contra Railway sería lo peor que este repositorio puede hacer, y **el `.env` del
repo apunta a producción**, así que el olvido de exportar una variable es todo lo
que separa una cosa de la otra.

Por eso el criterio del freno está al revés de lo natural: no busca señales de
producción para bloquear, **exige la prueba de que es local**. Estos tests
custodian esa dirección — la lista blanca de hosts, el nombre de la base y la URL
vacía— porque aflojar cualquiera de las tres deja pasar exactamente el caso que
no se puede permitir.

Estilo del proyecto: unitario puro. `verificar_destino` no lee el entorno, así
que se la puede probar contra la URL de producción sin tenerla configurada.

Ver §Sesión de carga.
"""

from __future__ import annotations

import pytest

from tests.carga import guardas

# La URL real de producción, con la clave cambiada. Es el caso que este freno
# existe para atajar.
PRODUCCION = "postgresql+psycopg://postgres:xxxx@zephyr.proxy.rlwy.net:26007/railway"
LOCAL = "postgresql+psycopg://postgres:postgres@127.0.0.1:5432/dailyfc_carga"


def test_la_base_de_produccion_se_rechaza() -> None:
    """Lo único que este módulo tiene que hacer bien."""
    with pytest.raises(guardas.DestinoProhibido):
        guardas.verificar_destino(PRODUCCION)


def test_una_base_local_pasa() -> None:
    guardas.verificar_destino(LOCAL)


def test_localhost_tambien_pasa() -> None:
    guardas.verificar_destino(
        "postgresql+psycopg://postgres:postgres@localhost:5432/dailyfc_test"
    )


def test_un_host_desconocido_se_rechaza_aunque_no_parezca_produccion() -> None:
    """La lista es blanca a propósito: lo que no está, no pasa.

    Al revés —bloquear solo lo que parezca producción— cualquier host nuevo
    entraría por defecto, y el default tiene que ser el seguro: lo peor de
    equivocarse acá es irreversible, y lo peor de equivocarse al revés es que
    alguien agregue una línea a la lista.
    """
    for url in (
        "postgresql+psycopg://u:p@db.interno.empresa:5432/pruebas",
        "postgresql+psycopg://u:p@192.168.1.50:5432/dailyfc",
        "postgresql+psycopg://u:p@algun-host.aws.com:5432/test",
    ):
        with pytest.raises(guardas.DestinoProhibido):
            guardas.verificar_destino(url)


def test_un_tunel_a_produccion_no_se_cuela_por_ser_local() -> None:
    """Un túnel SSH publica Railway en 127.0.0.1 y pasaría el chequeo de host.

    Por eso el nombre de la base también se mira: la de producción se llama
    `railway`, y ese nombre no aparece en ninguna base de prueba por accidente.
    """
    with pytest.raises(guardas.DestinoProhibido):
        guardas.verificar_destino("postgresql+psycopg://u:p@127.0.0.1:5432/railway")


def test_sin_database_url_no_arranca() -> None:
    """Vacía es el caso peligroso: el proyecto cae en el .env, que es producción."""
    with pytest.raises(guardas.DestinoProhibido):
        guardas.verificar_destino("")


def test_el_mensaje_dice_qué_hacer() -> None:
    """Un freno que no explica cómo seguir se termina salteando."""
    with pytest.raises(guardas.DestinoProhibido) as exc:
        guardas.verificar_destino(PRODUCCION)

    mensaje = str(exc.value)
    assert "zephyr.proxy.rlwy.net" in mensaje  # cuál era el destino
    assert "DATABASE_URL" in mensaje  # qué hay que cambiar


def test_telegram_configurado_es_una_advertencia_no_un_freno() -> None:
    """Frenar por esto sería exagerado: la sesión no manda los bugs uno por uno."""
    avisos = guardas.verificar_entorno(LOCAL, telegram_token="123:abc")
    assert any("TELEGRAM" in a for a in avisos)

    assert guardas.verificar_entorno(LOCAL, telegram_token="") == []


# ══════════════════════════════════════════════════════════════════════
#  El catálogo de invariantes
# ══════════════════════════════════════════════════════════════════════

def test_todos_los_invariantes_estan_en_el_catalogo() -> None:
    """Un invariante que no está en `TODOS` no se corre nunca.

    Y no falla nada: la sesión termina en verde informando que el negocio está
    sano, sin haber mirado justo lo que el invariante nuevo custodiaba. Es el
    mismo riesgo que el proyecto ya cubre con `_ENTIDADES` en la anulación y con
    `_ORIGENES_STOCK`, por la misma razón.
    """
    import inspect

    from tests.carga import invariantes

    publicas = {
        nombre
        for nombre, funcion in inspect.getmembers(invariantes, inspect.isfunction)
        if not nombre.startswith("_")
        and funcion.__module__ == invariantes.__name__
        and nombre != "verificar"
        # Los helpers de presentación no son chequeos.
        and inspect.signature(funcion).return_annotation == "list[Violacion]"
    }
    en_catalogo = {f.__name__ for f in invariantes.TODOS}

    assert publicas == en_catalogo, (
        f"Invariantes fuera del catálogo (no se corren): {publicas - en_catalogo}"
    )


def test_un_invariante_que_revienta_no_corta_la_sesion() -> None:
    """Mil operaciones perdidas porque una consulta falló sería el peor final.

    Y el fallo en sí es información: si la base quedó en un estado donde no se
    puede ni preguntar, eso también hay que anotarlo.
    """
    from tests.carga import invariantes

    class DbRota:
        def execute(self, *_a, **_k):
            raise RuntimeError("la conexión se cayó")

        def rollback(self):
            pass

    violaciones = invariantes.verificar(DbRota())

    assert violaciones, "tenía que reportar el fallo en vez de quedarse callado"
    assert all(v.clave.startswith("invariante-roto-") for v in violaciones)
