"""Smoke de la ganancia de cheques del reporte (§7), contra una base de verdad.

Los unitarios (`tests/test_ganancia_cheques.py`) prueban **la cuenta** de cada
cheque: cuánto deja uno vendido, uno cobrado, uno fiado. Lo que no pueden ver es
la otra mitad —la consulta—: que cada salida caiga en el día correcto, que el
fiado entre por `fiados.fecha_fiado` y no por el timestamp del cheque, y que un
cheque anulado o revertido deje de sumar. Eso necesita una base, y la suite del
proyecto es unitaria pura a propósito.

De ahí este script, en la misma línea que `smoke_echeq.py`: corre contra una base
LOCAL que crea y migra al momento, carga cheques por los **servicios reales** y
compara el reporte contra los números esperados.

No cuesta plata (no llama a ningún modelo) pero necesita PostgreSQL local.

Uso (desde `backend/`):
    .venv\\Scripts\\python.exe scripts/smoke_ganancia_cheques.py
    .venv\\Scripts\\python.exe scripts/smoke_ganancia_cheques.py --conservar

La base se llama `dailyfc_smoke_ganancia` y se borra al terminar salvo
`--conservar`, para poder mirarla con psql.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

_BASE = "dailyfc_smoke_ganancia"
_PG = Path(r"C:\Program Files\PostgreSQL\17\bin")
_URL = f"postgresql+psycopg://postgres:postgres@127.0.0.1:5432/{_BASE}"

# ── Guardas de entorno, ANTES de importar `app` ──────────────────────────────
# Asignación directa y no setdefault: el .env del repo apunta a producción y bajo
# `railway run` el entorno ya trae WAHA y Telegram reales.
os.environ["DATABASE_URL"] = _URL
os.environ["WAHA_API_URL"] = "http://127.0.0.1:9"
os.environ["TELEGRAM_BOT_TOKEN"] = ""
os.environ.setdefault("ADMIN_USERNAME", "smoke")
os.environ.setdefault("ADMIN_PASSWORD", "smoke1234")
os.environ.setdefault("SECRET_KEY", "smoke")
os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

_VERDE, _ROJO, _FIN = "\033[32m", "\033[31m", "\033[0m"

HOY = date.today()
AYER = HOY - timedelta(days=1)

_fallos: list[str] = []


def _color(txt: str, c: str) -> str:
    return f"{c}{txt}{_FIN}" if sys.stdout.isatty() else txt


def _check(nombre: str, obtenido, esperado) -> None:
    if obtenido == esperado:
        print(_color(f"  ✓ {nombre}: {obtenido}", _VERDE))
    else:
        print(_color(f"  ✗ {nombre}: {obtenido} (esperado {esperado})", _ROJO))
        _fallos.append(nombre)


def _psql(*sql: str, base: str = "postgres") -> None:
    cmd = [str(_PG / "psql.exe"), "-U", "postgres", "-h", "127.0.0.1", "-d", base, "-q"]
    for s in sql:
        cmd += ["-c", s]
    r = subprocess.run(
        cmd, env={**os.environ, "PGPASSWORD": "postgres"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        raise SystemExit(f"psql falló: {r.stdout}\n{r.stderr}")


def _crear_base() -> None:
    _psql(f"DROP DATABASE IF EXISTS {_BASE};", f"CREATE DATABASE {_BASE};")
    alembic = Path(__file__).resolve().parent.parent / ".venv" / "Scripts" / "alembic.exe"
    r = subprocess.run(
        [str(alembic), "upgrade", "head"],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={**os.environ, "DATABASE_URL": _URL},
        # `encoding` explícito: sin esto los acentos de las migraciones revientan
        # el hilo lector con UnicodeDecodeError y tapan la pantalla que hay que leer.
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(r.stdout, r.stderr, file=sys.stderr)
        raise SystemExit("No se pudo migrar la base de prueba.")


def _ts(d: date, hora: int = 11) -> datetime:
    """Timestamp UTC de un día local ART (UTC−3) a esa hora."""
    return datetime.combine(d, time(hora)).replace(tzinfo=UTC) + timedelta(hours=3)


def _correr() -> None:
    from sqlalchemy.orm import Session

    from app.db.models import ChequeEstado, MedioPago, Moneda, MovimientoEfectivoTipo
    from app.db.session import engine
    from app.schemas.cheques import (
        ChequeCreate,
        ChequeFiarRequest,
        ChequeManualTransition,
    )
    from app.schemas.clientes import ClienteCreate
    from app.schemas.movimientos import MovimientoEfectivoCreate
    from app.schemas.pasivos import PasivoCancelarConChequeRequest, PasivoCreate
    from app.services import anulacion as svc_anul
    from app.services import cheques as svc
    from app.services import clientes as svc_cli
    from app.services import movimientos as svc_mov
    from app.services import pasivos as svc_pas
    from app.services import reportes as svc_rep
    from app.services.whatsapp import dispatcher as disp

    with Session(engine) as db:
        cli = svc_cli.create_cliente(db, ClienteCreate(nombre="Cliente Smoke"))

        def alta(nro: str, monto: str, compra: str, f_compra: date = HOY, **extra):
            return svc.create_cheque(db, ChequeCreate(
                nro_cheque=nro, banco="Galicia", monto=Decimal(monto),
                porcentaje_compra=Decimal(compra),
                fecha_pago=f_compra + timedelta(days=60),
                medio_pago=MedioPago.EFECTIVO, **extra,
            ), created_at=_ts(f_compra, 10))

        def vender(cheque, venta: str, cuando: date = HOY):
            svc.transition_cheque(db, cheque.id, ChequeManualTransition(
                target_state=ChequeEstado.VENDIDO, operador_id="smoke", motivo="smoke",
                porcentaje_venta=Decimal(venta), medio_pago=MedioPago.EFECTIVO,
            ), event_at=_ts(cuando))

        def ganancia(desde: date, hasta: date):
            return svc_rep.get_reporte_caja(db, desde, hasta).ganancia_cheques

        # ── Las tres salidas que realizan ganancia ───────────────────────
        print("\n▸ Las tres salidas que realizan ganancia")
        vender(alta("90001", "1000000", "10"), "6")          # venta:  $40.000
        svc.transition_cheque(db, alta("90002", "500000", "8").id, ChequeManualTransition(
            target_state=ChequeEstado.COBRADO, operador_id="smoke", motivo="smoke",
            medio_pago=MedioPago.EFECTIVO), event_at=_ts(HOY))  # cobro:  $40.000
        svc.fiar_cheque(db, alta("90003", "1000000", "12").id, ChequeFiarRequest(
            operador_id="smoke", motivo="smoke", cliente_destino_id=cli.id,
            porcentaje_venta=Decimal("5")), fecha_fiado=HOY, event_at=_ts(HOY))  # $70.000

        g = ganancia(HOY, HOY)
        _check("venta", g.ventas, Decimal("40000.00"))
        _check("cobro al vencimiento (todo el descuento de compra)", g.cobros, Decimal("40000.00"))
        _check("fiado (se reconoce al entregar el papel)", g.fiados, Decimal("70000.00"))
        _check("total", g.total, Decimal("150000.00"))
        _check("cantidad", g.cantidad, 3)

        # ── Lo que NO suma ───────────────────────────────────────────────
        print("\n▸ Lo que no suma")
        alta("90004", "300000", "15")  # sigue en cartera
        svc.transition_cheque(db, alta("90005", "200000", "10").id, ChequeManualTransition(
            target_state=ChequeEstado.RECHAZADO, operador_id="smoke", motivo="smoke"),
            event_at=_ts(HOY))
        g = ganancia(HOY, HOY)
        _check("el cheque en cartera no gana nada todavía", g.total, Decimal("150000.00"))
        _check("el rechazo va aparte y no resta", g.rechazos, Decimal("180000.00"))
        _check("el rechazo tampoco entra en la cantidad", g.cantidad, 3)

        # ── El filtro de fechas ──────────────────────────────────────────
        print("\n▸ El filtro de fechas")
        vender(alta("90006", "1000000", "20", f_compra=AYER), "10", cuando=AYER)
        _check("lo de ayer no entra en el reporte de hoy", ganancia(HOY, HOY).total,
               Decimal("150000.00"))
        _check("y sí en el de ayer", ganancia(AYER, AYER).total, Decimal("100000.00"))
        _check("el rango suma los dos días", ganancia(AYER, HOY).total, Decimal("250000.00"))
        _check("y cuenta los cuatro cheques", ganancia(AYER, HOY).cantidad, 4)

        # ── El cheque entregado a un acreedor (§5) ───────────────────────
        # Sale de cartera SIN dejar línea de caja: por el libro no se vería, y es
        # el motivo de que el dato se calcule desde la tabla `cheques`.
        print("\n▸ Entregado a un acreedor para pagarle una deuda")
        pasivo = svc_pas.create_pasivo(db, PasivoCreate(
            acreedor="Proveedor SA", concepto="mercadería",
            monto=Decimal("900000"), moneda=Moneda.ARS))
        entregado = alta("90007", "1000000", "12")
        svc_pas.cancelar_con_cheque(db, pasivo.id, PasivoCancelarConChequeRequest(
            cheque_id=entregado.id, porcentaje_venta=Decimal("6"),
            operador_id="smoke", motivo="pago al proveedor",
            vuelto_modo="QUEDA_DEBIENDO"))
        _check("la entrega suma como una venta", ganancia(HOY, HOY).ventas,
               Decimal("100000.00"))

        # ── Anular y revertir ────────────────────────────────────────────
        print("\n▸ Anular y revertir dejan de sumar")
        anulado = alta("90008", "800000", "10")
        vender(anulado, "5")
        _check("la venta suma", ganancia(HOY, HOY).ventas, Decimal("140000.00"))
        svc_anul.anular(db, "cheque", anulado.id, operador_id="smoke", motivo="mal cargado")
        _check("anulado deja de sumar", ganancia(HOY, HOY).ventas, Decimal("100000.00"))

        revertido = alta("90009", "600000", "12")
        vender(revertido, "6")
        _check("la segunda venta suma", ganancia(HOY, HOY).ventas, Decimal("136000.00"))
        svc_anul.revertir_cheque(db, revertido.id, operador_id="smoke", motivo="se cayó")
        _check("revertido deja de sumar", ganancia(HOY, HOY).ventas, Decimal("100000.00"))

        # ── Comprado en dólares o a deber ────────────────────────────────
        # La ganancia es sobre el NOMINAL: no cambia porque el precio se haya
        # pagado con billetes o haya quedado a deber (§Cheque pagado en dólares).
        print("\n▸ Comprado en dólares o a deber")
        svc_mov.create_movimiento(db, MovimientoEfectivoCreate(
            tipo=MovimientoEfectivoTipo.COMPRA, moneda=Moneda.USD,
            monto=Decimal("1000"), cotizacion_aplicada=Decimal("950"),
            fecha_operacion=_ts(HOY, 9)))
        en_usd = alta("90010", "1000000", "10", usd_entregados=Decimal("600"),
                      cotizacion_usd=Decimal("1000"), monto_abonado=Decimal("300000"))
        vender(en_usd, "5")
        db.refresh(en_usd)
        _check("pagado en dólares: la ganancia es sobre el nominal",
               svc.ganancia_realizada(en_usd), Decimal("50000.00"))

        a_deber = alta("90011", "2000000", "15", monto_abonado=Decimal("500000"),
                       cliente_origen_id=cli.id)
        vender(a_deber, "8")
        db.refresh(a_deber)
        _check("comprado a deber: la ganancia es sobre el nominal",
               svc.ganancia_realizada(a_deber), Decimal("140000.00"))

        # ── El bot dice lo mismo que el panel ────────────────────────────
        print("\n▸ El bot dice el mismo número")
        texto = disp._consulta_caja(db, HOY, HOY, {}, "hoy")
        total = ganancia(HOY, HOY).total
        if f"Ganancia por cheques: ${total:,.2f}".replace(",", ".") not in texto.replace(",", "."):
            _check("la consulta de caja del bot muestra el total", texto, f"…{total}…")
        else:
            print(_color(f"  ✓ el bot contesta la ganancia de cheques: {total}", _VERDE))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--conservar", action="store_true",
                    help="no borrar la base al terminar, para mirarla con psql")
    args = ap.parse_args()

    _crear_base()
    try:
        _correr()
    finally:
        if not args.conservar:
            # El pool del engine deja conexiones abiertas aunque la sesión ya
            # haya cerrado, y Postgres se niega a borrar una base en uso.
            from app.db.session import engine

            engine.dispose()
            _psql(f"DROP DATABASE IF EXISTS {_BASE};")

    if _fallos:
        print(_color(f"\n{len(_fallos)} falla(n): {', '.join(_fallos)}", _ROJO))
        return 1
    print(_color("\nTodo bien.", _VERDE))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
