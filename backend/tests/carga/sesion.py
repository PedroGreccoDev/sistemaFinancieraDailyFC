"""La sesión de carga: mil operaciones al azar buscando lo que se rompe.

    cd backend
    .\\.venv\\Scripts\\python.exe -m tests.carga.sesion --corridas 1000

Encadena operaciones del negocio —altas de cheques, ventas, cobros, pagos,
divisas, traspasos, consultas y reportes— eligiéndolas con una semilla fija, y
después de cada tanda pregunta si el negocio sigue siendo coherente. Todo lo que
falle entra en la tabla `bugs` con su número y con la corrida que lo encontró.

**Busca dos cosas distintas, y la segunda es la que importa:**

1. Lo que revienta. Una excepción en el bot o un 500 del panel: eso ya lo anota
   el registro de bugs solo, acá solo se cuenta.
2. Lo que **no** revienta y sin embargo está mal. La caja que no cuadra contra
   el stock, el fiado cancelado que sigue debiendo, la línea de caja de una
   operación anulada. Nada falla, el operador no ve nada, y el descuadre aparece
   al cierre del mes. Eso lo cazan los invariantes (ver `invariantes.py`).

**No manda los bugs por Telegram uno por uno.** Una sesión puede provocar
cientos de errores a propósito: se escriben con `drenar_sync` y al final sale
**un** mensaje con el resumen. Un chat con mil avisos no lo lee nadie, que es lo
mismo que no tener avisos.

Sobre el arranque: no se usa el `lifespan` de la app a propósito. El drenador de
fondo mandaría cada bug a Telegram, que es justo lo que no se quiere; la captura
de logs se instala a mano y la escritura la maneja la sesión.

Ver §Sesión de carga.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import random
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

# Permite `python -m tests.carga.sesion` desde `backend/`.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.core.config import get_settings  # noqa: E402
from app.db.session import SessionLocal  # noqa: E402
from app.services import bugs, bugs_reporte, telegram  # noqa: E402
from tests.carga import escenarios, frases, guardas, invariantes  # noqa: E402

logger = logging.getLogger("sesion-carga")

DOCUMENTO = Path(__file__).resolve().parents[3] / "docs" / "BUGS.md"


# ══════════════════════════════════════════════════════════════════════
#  Preparación
# ══════════════════════════════════════════════════════════════════════

def _nombre_de_sesion(momento: datetime, semilla: int) -> str:
    """Identifica la corrida. Lleva la semilla porque es lo que la reproduce."""
    return f"{momento.strftime('%Y%m%d-%H%M%S')}-s{semilla}"


def _preparar_base(db, rng: random.Random) -> None:
    """Deja el sistema como un negocio que ya venía andando.

    Sin apertura, la caja arranca en cero y en dólares no hay stock: media
    sesión se iría en rechazos de "no hay stock" sin llegar a ejercitar nada.
    """
    from app.services import apertura as svc_apertura
    from app.services.usuarios import bootstrap_admin

    bootstrap_admin(db)

    try:
        svc_apertura.definir_saldo_inicial(
            db,
            saldo_ars=Decimal("5000000.00"),
            saldo_usd=Decimal("10000.00"),
            saldo_ars_transf=Decimal("3000000.00"),
            # Los dólares van todos al efectivo: **el negocio no tiene cuenta
            # bancaria en dólares** (dicho por el dueño, 2026-08-25). Cargarlos
            # como depositados probaría un negocio que no es este, y además tapa
            # los hallazgos de verdad: la apertura no le crea lote de stock a esa
            # plata, así que el descuadre de USD se lleva puesta la corrida
            # entera y ningún otro invariante llega a verse.
            saldo_usd_transf=Decimal("0"),
            fecha=date.today(),
            operador_id="carga",
            cotizacion_usd=Decimal("1200"),
            forzar=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"  (apertura omitida: {type(exc).__name__}: {exc})")
        db.rollback()


def _cliente_panel():
    """El panel con un admin logueado, o `None` si no se pudo."""
    from fastapi.testclient import TestClient

    from app.main import app

    settings = get_settings()
    # Sin lifespan a propósito (ver el docstring del módulo).
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post(
        "/api/v1/auth/login",
        json={
            "username": settings.admin_username,
            "password": settings.admin_password,
        },
    )
    if resp.status_code != 200:
        print(f"  (panel deshabilitado: el login dio HTTP {resp.status_code})")
        return None, {}
    return client, {"Authorization": f"Bearer {resp.json()['token']}"}


# ══════════════════════════════════════════════════════════════════════
#  La corrida
# ══════════════════════════════════════════════════════════════════════

def _anotar_violaciones(violaciones, sesion: str, corrida: int) -> None:
    """Convierte cada invariante roto en un bug con número.

    La `clave` va como ubicación para que la huella sea estable: el mismo
    invariante roto en dos corridas es **un** bug con dos ocurrencias, no dos.
    """
    for v in violaciones:
        bugs.capturar_mensaje(
            origen=bugs.ORIGEN_TESTING,
            titulo=v.titulo,
            tipo="InvarianteRoto",
            ubicacion=v.clave,
            ambito=f"invariante:{v.clave}",
            detalle=f"{v.detalle}\n\n(detectado en la corrida #{corrida})",
            sesion_test=sesion,
        )


def correr(
    *,
    corridas: int,
    semilla: int,
    verificar_cada: int,
    con_panel: bool,
) -> dict:
    arranque = time.monotonic()
    inicio = datetime.now(timezone.utc)
    sesion = _nombre_de_sesion(inicio, semilla)
    rng = random.Random(semilla)

    bugs.marcar_sesion(sesion)
    bugs.instalar_captura_de_logs()

    db = SessionLocal()
    print(f"Preparando la base…")
    _preparar_base(db, rng)

    client, headers = (None, {})
    if con_panel:
        client, headers = _cliente_panel()

    ctx = escenarios.Contexto(
        db=db, client=client, headers=headers, rng=rng,
        phone="5490000000000", sesion=sesion,
    )

    por_escenario: Counter = Counter()
    rechazos: Counter = Counter()
    fallas: Counter = Counter()
    violaciones_vistas: Counter = Counter()

    print(f"Corriendo {corridas} operaciones (semilla {semilla})…\n")
    for n in range(1, corridas + 1):
        nombre, funcion = escenarios.elegir(rng)
        por_escenario[nombre] += 1

        # **Una sesión por operación, igual que en producción.** El webhook abre
        # su `SessionLocal()` por mensaje y la cierra al terminar; con una sola
        # sesión para toda la corrida, una operación rechazada deja sus escrituras
        # pendientes y **el commit de la siguiente las escribe**. Eso llenó la
        # primera versión de esta sesión de descuadres que en producción no
        # existen: líneas de caja de cobros que el sistema había rechazado.
        ctx.db = db = SessionLocal()
        try:
            resultado = funcion(ctx)
        except Exception as exc:  # noqa: BLE001
            # Un escenario que revienta por fuera del sistema es un bug del
            # propio banco de pruebas, y también hay que verlo.
            fallas[nombre] += 1
            bugs.capturar(
                exc,
                origen=bugs.ORIGEN_TESTING,
                ambito=f"escenario:{nombre}",
                sesion_test=sesion,
            )
            resultado = None
        finally:
            # Lo que no se commiteó se descarta, que es lo que hace el `close()`
            # del webhook: una operación a medias no puede sobrevivir al mensaje.
            db.rollback()
            db.close()

        if resultado is not None:
            if not resultado.ok:
                fallas[nombre] += 1
            elif resultado.rechazo:
                rechazos[nombre] += 1

        if n % verificar_cada == 0 or n == corridas:
            # Sesión propia también para verificar: los invariantes solo leen, y
            # tienen que ver lo que quedó **commiteado**, no lo que alguna
            # operación dejó a medias en la sesión de al lado.
            chequeo = SessionLocal()
            try:
                encontradas = invariantes.verificar(chequeo)
            except Exception as exc:  # noqa: BLE001
                encontradas = []
                bugs.capturar(
                    exc, origen=bugs.ORIGEN_TESTING, ambito="invariantes", sesion_test=sesion
                )
            finally:
                chequeo.close()

            for v in encontradas:
                violaciones_vistas[v.clave] += 1
            _anotar_violaciones(encontradas, sesion, n)
            bugs.drenar_sync()

        if n % max(1, corridas // 20) == 0:
            hechas = sum(rechazos.values()) + sum(fallas.values())
            print(
                f"  {n:>5}/{corridas}  ·  fallas {sum(fallas.values()):>4}  ·  "
                f"rechazos {sum(rechazos.values()):>4}  ·  "
                f"invariantes rotos {sum(violaciones_vistas.values()):>3}"
            )

    registrados = bugs.drenar_sync()
    lectura = SessionLocal()
    try:
        resumen_bugs = bugs_reporte.resumir(lectura, sesion_test=sesion)
        todos = bugs_reporte.listar(lectura, limite=2000)
    finally:
        lectura.close()

    bugs.marcar_sesion(None)
    bugs.desinstalar_captura_de_logs()

    return {
        "sesion": sesion,
        "corridas": corridas,
        "semilla": semilla,
        "segundos": round(time.monotonic() - arranque, 1),
        "por_escenario": por_escenario,
        "rechazos": rechazos,
        "fallas": fallas,
        "violaciones": violaciones_vistas,
        "resumen_bugs": resumen_bugs,
        "todos_los_bugs": todos,
        "registrados_al_final": len(registrados),
    }


# ══════════════════════════════════════════════════════════════════════
#  Salida
# ══════════════════════════════════════════════════════════════════════

def correr_ia_real(cantidad: int, semilla: int, sesion: str) -> dict:
    """Le manda frases de verdad al modelo y verifica que entienda cuál es cuál.

    Es la parte que el resto de la sesión no puede probar: `dispatch` recibe el
    intent ya resuelto. Son pocas llamadas y elegidas —las frases que ya salieron
    mal alguna vez (ver `frases.py`)— porque cada una cuesta plata y tarda.

    Una clasificación equivocada **es un bug**: el intent decide para qué lado se
    mueve la caja, y confundir "me pagó" con "le pagué" la mueve al revés.
    """
    from app.services.ia import motor

    rng = random.Random(semilla)
    elegidas = rng.sample(frases.FRASES, min(cantidad, len(frases.FRASES)))

    aciertos, errores = 0, []
    print(f"\nProbando el modelo con {len(elegidas)} frases reales…")

    for texto, esperado, porque in elegidas:
        try:
            resultado = asyncio.run(motor.extraer_intencion(texto, None, []))
            obtenido = resultado.intent
        except Exception as exc:  # noqa: BLE001
            obtenido = f"(falló: {type(exc).__name__})"
            bugs.capturar(
                exc, origen=bugs.ORIGEN_BOT, ambito="ia:extraer_intencion",
                sesion_test=sesion,
            )

        if obtenido == esperado:
            aciertos += 1
            print(f"  ✓ {texto[:52]:<52} → {obtenido}")
            continue

        errores.append((texto, esperado, obtenido, porque))
        print(f"  ✗ {texto[:52]:<52} → {obtenido} (esperaba {esperado})")
        bugs.capturar_mensaje(
            origen=bugs.ORIGEN_BOT,
            titulo=f"El modelo leyó «{esperado}» como «{obtenido}»",
            tipo="ClasificacionIncorrecta",
            # La huella agrupa por par esperado→obtenido: la misma confusión con
            # otra frase es el mismo problema, no un bug nuevo.
            ubicacion=f"{esperado}->{obtenido}",
            ambito=f"ia:{esperado}",
            detalle=f"Frase: {texto}\nEsperado: {esperado}\nDevolvió: {obtenido}\n\nPor qué importa: {porque}",
            sesion_test=sesion,
        )

    bugs.drenar_sync()
    return {"probadas": len(elegidas), "aciertos": aciertos, "errores": errores}


def _imprimir_resumen(r: dict) -> None:
    print()
    print("=" * 66)
    print(f"  Sesión {r['sesion']} — {r['corridas']} corridas en {r['segundos']}s")
    print("=" * 66)

    fallas = sum(r["fallas"].values())
    rechazos = sum(r["rechazos"].values())
    print(f"  Operaciones que fallaron : {fallas}")
    print(f"  Rechazadas por el sistema: {rechazos}  (validaciones: no son errores)")
    print(f"  Invariantes rotos        : {sum(r['violaciones'].values())}")

    b = r["resumen_bugs"]
    print()
    print(f"  Bugs de esta sesión: {b.total}  "
          f"({b.abiertos} abiertos, {b.cerrados} cerrados) · "
          f"{b.ocurrencias} ocurrencias")
    if b.por_origen:
        print(f"  Por origen: {dict(b.por_origen)}")

    if r.get("ia"):
        ia = r["ia"]
        print()
        print(f"  Modelo real: {ia['aciertos']}/{ia['probadas']} frases bien clasificadas")
        for texto, esperado, obtenido, _ in ia["errores"]:
            print(f"    ✗ «{texto[:44]}» → {obtenido} (esperaba {esperado})")

    if r["violaciones"]:
        print()
        print("  Invariantes rotos (lo que no dio ninguna señal):")
        for clave, veces in r["violaciones"].most_common():
            print(f"    · {clave}  ×{veces}")

    if r["fallas"]:
        print()
        print("  Escenarios que más fallaron:")
        for nombre, veces in r["fallas"].most_common(8):
            de = r["por_escenario"][nombre]
            print(f"    · {nombre:<24} {veces:>4} de {de}")

    print()
    print("  Los bugs, con su número y su detalle, en docs/BUGS.md")
    print("=" * 66)


def _texto_telegram(r: dict) -> str:
    b = r["resumen_bugs"]
    fallas = sum(r["fallas"].values())
    rotos = sum(r["violaciones"].values())

    icono = "✅" if (fallas == 0 and rotos == 0) else "🐛"
    lineas = [
        f"{icono} <b>Sesión de carga terminada</b>",
        "",
        f"{r['corridas']} operaciones en {r['segundos']}s (semilla {r['semilla']})",
        f"Fallaron: {fallas} · Invariantes rotos: {rotos}",
        f"Bugs de la sesión: {b.total} ({b.abiertos} abiertos)",
    ]
    if r["violaciones"]:
        lineas.append("")
        lineas.append("<b>Sin dar ninguna señal:</b>")
        for clave, veces in r["violaciones"].most_common(5):
            lineas.append(f"· {telegram.escapar(clave)} ×{veces}")
    return "\n".join(lineas)


def _escribir_documento(r: dict) -> None:
    texto = bugs_reporte.render_markdown(
        r["todos_los_bugs"], generado_en=datetime.now(timezone.utc)
    )
    DOCUMENTO.parent.mkdir(parents=True, exist_ok=True)
    DOCUMENTO.write_text(texto, encoding="utf-8", newline="\n")
    print(f"  Documento actualizado: {DOCUMENTO}")


# ══════════════════════════════════════════════════════════════════════
#  Entrada
# ══════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Sesión de carga: opera el sistema al azar y anota lo que se rompe."
    )
    parser.add_argument("--corridas", type=int, default=1000)
    parser.add_argument(
        "--semilla", type=int, default=42,
        help="Misma semilla = misma sesión, operación por operación.",
    )
    parser.add_argument(
        "--verificar-cada", type=int, default=10,
        help="Cada cuántas operaciones se chequean los invariantes.",
    )
    parser.add_argument("--sin-panel", action="store_true", help="Solo el bot.")
    parser.add_argument(
        "--ia-real", type=int, default=0, metavar="N",
        help=(
            "Además, probar N frases contra el modelo DE VERDAD (cuesta plata y "
            "tarda). Son las frases que ya salieron mal alguna vez: ver frases.py."
        ),
    )
    parser.add_argument(
        "--telegram", action="store_true",
        help="Manda el resumen final por Telegram (uno solo, no los bugs).",
    )
    args = parser.parse_args(argv)

    # La consola de Windows sale en cp1252 y cualquier acento la voltea con un
    # UnicodeEncodeError — que además taparía el mensaje que se estaba
    # imprimiendo, incluido el del freno de producción, que es el que hay que
    # poder leer sí o sí. `errors="replace"` cambia un carácter raro por un
    # signo de pregunta en vez de romper.
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass

    logging.basicConfig(level=logging.CRITICAL)  # los errores se ven en los bugs

    settings = get_settings()

    # ── El freno. Antes que cualquier otra cosa. ──────────────────────
    try:
        guardas.verificar_destino(settings.database_url)
    except guardas.DestinoProhibido as exc:
        print("\n╔══════════════════════════════════════════════════════════╗")
        print("║  LA SESIÓN NO ARRANCA                                    ║")
        print("╚══════════════════════════════════════════════════════════╝")
        print(f"\n{exc}\n")
        return 2

    for aviso in guardas.verificar_entorno(settings.database_url, settings.telegram_bot_token):
        print(f"  ⚠️  {aviso}")

    resultado = correr(
        corridas=args.corridas,
        semilla=args.semilla,
        verificar_cada=args.verificar_cada,
        con_panel=not args.sin_panel,
    )

    if args.ia_real > 0:
        resultado["ia"] = correr_ia_real(args.ia_real, args.semilla, resultado["sesion"])
        # Lo que el modelo entendió mal también entra en los bugs de la sesión.
        lectura = SessionLocal()
        try:
            resultado["resumen_bugs"] = bugs_reporte.resumir(
                lectura, sesion_test=resultado["sesion"]
            )
            resultado["todos_los_bugs"] = bugs_reporte.listar(lectura, limite=2000)
        finally:
            lectura.close()

    _imprimir_resumen(resultado)
    _escribir_documento(resultado)

    if args.telegram and telegram.configurado():
        asyncio.run(telegram.enviar_alerta(_texto_telegram(resultado)))
        print("  Resumen enviado por Telegram.")

    # Sale distinto de cero si encontró algo: sirve para encadenarlo en un script.
    hubo_hallazgos = (
        sum(resultado["fallas"].values()) or sum(resultado["violaciones"].values())
    )
    return 1 if hubo_hallazgos else 0


if __name__ == "__main__":
    raise SystemExit(main())
