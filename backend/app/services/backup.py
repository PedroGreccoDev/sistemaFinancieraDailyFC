from __future__ import annotations

import base64
from datetime import UTC, date, datetime, time
from decimal import Decimal
from io import BytesIO
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, undefer

from app.db.models import (
    Cheque,
    Cliente,
    Cuota,
    Fiado,
    GastoOperativo,
    MovimientoEfectivo,
    Pasivo,
    Prestamo,
)

BACKUP_VERSION = 1
ALEMBIC_REVISION = "0010"

# ── Columnas por tabla (excluye computed/deferred) ──────────────────────────

_CL = ["id", "nombre", "cuit", "telefono", "created_at", "updated_at"]
_CH = [
    "id", "nro_cheque", "banco", "monto", "fecha_emision", "fecha_pago",
    "porcentaje_compra", "porcentaje_venta", "ganancia", "estado",
    "ultimo_evento_manual_at", "ultimo_operador_id", "ultimo_motivo_manual",
    "foto", "foto_mime", "cliente_origen_id", "cliente_destino_id",
    "created_at", "updated_at",
]
_PR = [
    "id", "cliente_id", "credito", "moneda", "cuotas", "frecuencia",
    "total_a_cobrar", "ganancia", "estado", "fecha_inicio", "created_at", "updated_at",
]
_CU = [
    "id", "prestamo_id", "numero_cuota", "fecha_vencimiento", "monto",
    "estado", "fecha_cobro", "created_at", "updated_at",
]
_MO = [
    "id", "cliente_id", "tipo", "moneda", "monto", "cotizacion_aplicada",
    "ganancia", "fecha_operacion", "observaciones", "created_at", "updated_at",
]
_FI = [
    "id", "cheque_id", "cliente_id", "monto_original", "porcentaje_venta",
    "saldo_pendiente", "estado", "fecha_fiado", "created_at", "updated_at",
]
_PA = [
    "id", "acreedor", "concepto", "monto", "saldo_pendiente", "moneda",
    "estado", "fecha_vencimiento", "fecha_cancelacion", "observaciones",
    "created_at", "updated_at",
]
_GA = [
    "id", "concepto", "monto", "moneda", "fecha_operacion", "hora_operacion",
    "observaciones", "created_at", "updated_at",
]

# ── Tipos para deserialización en importar ──────────────────────────────────

_UUID_COLS = frozenset({
    "id", "cliente_id", "cheque_id", "prestamo_id",
    "cliente_origen_id", "cliente_destino_id",
})
_DEC_COLS = frozenset({
    "monto", "credito", "total_a_cobrar", "ganancia",
    "porcentaje_compra", "porcentaje_venta", "cotizacion_aplicada",
    "monto_original", "saldo_pendiente",
})
_DT_COLS = frozenset({"created_at", "updated_at", "ultimo_evento_manual_at"})
_BYTES_COLS = frozenset({"foto"})


# ── Serialización ───────────────────────────────────────────────────────────

def _out(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bytes):
        return base64.b64encode(v).decode()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if hasattr(v, "value"):
        return v.value
    return v


def _serialize(row: Any, cols: list[str]) -> dict:
    return {c: _out(getattr(row, c)) for c in cols}


def exportar_json(db: Session) -> dict:
    cheques = db.query(Cheque).options(undefer(Cheque.foto)).all()
    return {
        "version": BACKUP_VERSION,
        "exported_at": datetime.now(tz=UTC).isoformat(),
        "alembic_revision": ALEMBIC_REVISION,
        "tablas": {
            "clientes":             [_serialize(r, _CL) for r in db.query(Cliente).all()],
            "cheques":              [_serialize(r, _CH) for r in cheques],
            "prestamos":            [_serialize(r, _PR) for r in db.query(Prestamo).all()],
            "cuotas":               [_serialize(r, _CU) for r in db.query(Cuota).all()],
            "movimientos_efectivo": [_serialize(r, _MO) for r in db.query(MovimientoEfectivo).all()],
            "fiados":               [_serialize(r, _FI) for r in db.query(Fiado).all()],
            "pasivos":              [_serialize(r, _PA) for r in db.query(Pasivo).all()],
            "gastos_operativos":    [_serialize(r, _GA) for r in db.query(GastoOperativo).all()],
        },
    }


# ── Deserialización ─────────────────────────────────────────────────────────

def _cv(
    row: dict,
    date_cols: frozenset[str] = frozenset(),
    dt_extra: frozenset[str] = frozenset(),
    time_cols: frozenset[str] = frozenset(),
) -> dict:
    r: dict = {}
    for k, v in row.items():
        if v is None:
            r[k] = None
        elif k in _UUID_COLS:
            r[k] = UUID(v) if isinstance(v, str) else v
        elif k in _DEC_COLS:
            r[k] = Decimal(str(v))
        elif k in _DT_COLS or k in dt_extra:
            r[k] = datetime.fromisoformat(v) if isinstance(v, str) else v
        elif k in date_cols:
            r[k] = date.fromisoformat(v) if isinstance(v, str) else v
        elif k in time_cols:
            r[k] = time.fromisoformat(v) if isinstance(v, str) else v
        elif k in _BYTES_COLS:
            r[k] = base64.b64decode(v) if isinstance(v, str) else v
        else:
            r[k] = v
    return r


_DATE_CH = frozenset({"fecha_emision", "fecha_pago"})
_DATE_PR = frozenset({"fecha_inicio"})
_DATE_CU = frozenset({"fecha_vencimiento", "fecha_cobro"})
_DATE_FI = frozenset({"fecha_fiado"})
_DATE_PA = frozenset({"fecha_vencimiento", "fecha_cancelacion"})
_DATE_GA = frozenset({"fecha_operacion"})
_TIME_GA = frozenset({"hora_operacion"})
_DT_MO   = frozenset({"fecha_operacion"})


def importar_json(db: Session, data: dict) -> dict[str, int]:
    if data.get("version") != BACKUP_VERSION:
        raise ValueError(
            f"Versión de backup incompatible: {data.get('version')!r}. "
            f"Se esperaba {BACKUP_VERSION}."
        )

    tablas = data.get("tablas", {})

    try:
        for tbl in (
            "cuotas", "fiados", "movimientos_efectivo", "prestamos",
            "cheques", "pasivos", "gastos_operativos", "clientes",
        ):
            db.execute(sa.text(f"DELETE FROM {tbl}"))  # noqa: S608

        def bulk(model: Any, rows: list[dict]) -> None:
            if rows:
                db.execute(sa.insert(model), rows)

        bulk(Cliente,           [_cv(r) for r in tablas.get("clientes", [])])
        bulk(Cheque,            [_cv(r, date_cols=_DATE_CH) for r in tablas.get("cheques", [])])
        bulk(Prestamo,          [_cv(r, date_cols=_DATE_PR) for r in tablas.get("prestamos", [])])
        bulk(Cuota,             [_cv(r, date_cols=_DATE_CU) for r in tablas.get("cuotas", [])])
        bulk(MovimientoEfectivo,[_cv(r, dt_extra=_DT_MO) for r in tablas.get("movimientos_efectivo", [])])
        bulk(Fiado,             [_cv(r, date_cols=_DATE_FI) for r in tablas.get("fiados", [])])
        bulk(Pasivo,            [_cv(r, date_cols=_DATE_PA) for r in tablas.get("pasivos", [])])
        bulk(GastoOperativo,    [_cv(r, date_cols=_DATE_GA, time_cols=_TIME_GA) for r in tablas.get("gastos_operativos", [])])

        db.commit()
    except Exception:
        db.rollback()
        raise

    tabla_names = (
        "clientes", "cheques", "prestamos", "cuotas",
        "movimientos_efectivo", "fiados", "pasivos", "gastos_operativos",
    )
    return {t: len(tablas.get(t, [])) for t in tabla_names}


# ── Excel ───────────────────────────────────────────────────────────────────

def _fmt_excel(v: Any) -> Any:
    if v is None:
        return ""
    if isinstance(v, UUID):
        return str(v)
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, bytes):
        return f"[imagen {len(v)} bytes]"
    if isinstance(v, datetime):
        return v.replace(tzinfo=None)
    if isinstance(v, time):
        return v.strftime("%H:%M:%S")
    if hasattr(v, "value"):
        return v.value
    return v


def exportar_excel(db: Session) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    HEADER_FILL = PatternFill("solid", fgColor="4F46E5")
    HEADER_FONT = Font(bold=True, color="FFFFFF", size=10)
    ALT_FILL    = PatternFill("solid", fgColor="F1F5F9")

    wb = Workbook()
    wb.remove(wb.active)  # type: ignore[arg-type]

    def add_sheet(title: str, headers: list[str], data_rows: list[list]) -> None:
        ws = wb.create_sheet(title)
        for ci, h in enumerate(headers, 1):
            cell = ws.cell(row=1, column=ci, value=h)
            cell.font = HEADER_FONT
            cell.fill = HEADER_FILL
            cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 20
        for ri, row in enumerate(data_rows, 2):
            fill = ALT_FILL if ri % 2 == 0 else None
            for ci, val in enumerate(row, 1):
                cell = ws.cell(row=ri, column=ci, value=val)
                if fill:
                    cell.fill = fill
        for ci in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(ci)].width = 20

    # Clientes
    clientes = db.query(Cliente).all()
    add_sheet(
        "Clientes",
        ["ID", "Nombre", "CUIT", "Teléfono", "Creado"],
        [[_fmt_excel(r.id), r.nombre, r.cuit, r.telefono, _fmt_excel(r.created_at)]
         for r in clientes],
    )

    # Cheques (sin foto, con tiene_foto)
    cheques = db.query(Cheque).all()
    add_sheet(
        "Cheques",
        ["ID", "Nro Cheque", "Banco", "Monto", "Fecha Emisión", "Fecha Pago",
         "% Compra", "% Venta", "Ganancia", "Estado", "Tiene Foto",
         "Cliente Origen ID", "Cliente Destino ID", "Creado"],
        [[
            _fmt_excel(r.id), r.nro_cheque, r.banco, _fmt_excel(r.monto),
            _fmt_excel(r.fecha_emision), _fmt_excel(r.fecha_pago),
            _fmt_excel(r.porcentaje_compra), _fmt_excel(r.porcentaje_venta),
            _fmt_excel(r.ganancia), _fmt_excel(r.estado),
            "Sí" if r.tiene_foto else "No",
            _fmt_excel(r.cliente_origen_id), _fmt_excel(r.cliente_destino_id),
            _fmt_excel(r.created_at),
        ] for r in cheques],
    )

    # Préstamos
    prestamos = db.query(Prestamo).all()
    add_sheet(
        "Préstamos",
        ["ID", "Cliente ID", "Crédito", "Moneda", "Cuotas", "Frecuencia",
         "Total a Cobrar", "Ganancia", "Estado", "Fecha Inicio", "Creado"],
        [[
            _fmt_excel(r.id), _fmt_excel(r.cliente_id),
            _fmt_excel(r.credito), _fmt_excel(r.moneda),
            r.cuotas, _fmt_excel(r.frecuencia),
            _fmt_excel(r.total_a_cobrar), _fmt_excel(r.ganancia),
            _fmt_excel(r.estado), _fmt_excel(r.fecha_inicio), _fmt_excel(r.created_at),
        ] for r in prestamos],
    )

    # Cuotas
    cuotas = db.query(Cuota).all()
    add_sheet(
        "Cuotas",
        ["ID", "Préstamo ID", "Nro Cuota", "Vencimiento", "Monto", "Estado",
         "Fecha Cobro", "Creado"],
        [[
            _fmt_excel(r.id), _fmt_excel(r.prestamo_id), r.numero_cuota,
            _fmt_excel(r.fecha_vencimiento), _fmt_excel(r.monto), _fmt_excel(r.estado),
            _fmt_excel(r.fecha_cobro), _fmt_excel(r.created_at),
        ] for r in cuotas],
    )

    # Movimientos
    movimientos = db.query(MovimientoEfectivo).all()
    add_sheet(
        "Movimientos",
        ["ID", "Cliente ID", "Tipo", "Moneda", "Monto", "Cotización",
         "Ganancia", "Fecha Operación", "Observaciones", "Creado"],
        [[
            _fmt_excel(r.id), _fmt_excel(r.cliente_id), _fmt_excel(r.tipo),
            _fmt_excel(r.moneda), _fmt_excel(r.monto), _fmt_excel(r.cotizacion_aplicada),
            _fmt_excel(r.ganancia), _fmt_excel(r.fecha_operacion),
            r.observaciones, _fmt_excel(r.created_at),
        ] for r in movimientos],
    )

    # Fiados
    fiados = db.query(Fiado).all()
    add_sheet(
        "Fiados",
        ["ID", "Cheque ID", "Cliente ID", "Monto Original", "% Venta",
         "Saldo Pendiente", "Estado", "Fecha Fiado", "Creado"],
        [[
            _fmt_excel(r.id), _fmt_excel(r.cheque_id), _fmt_excel(r.cliente_id),
            _fmt_excel(r.monto_original), _fmt_excel(r.porcentaje_venta),
            _fmt_excel(r.saldo_pendiente), _fmt_excel(r.estado),
            _fmt_excel(r.fecha_fiado), _fmt_excel(r.created_at),
        ] for r in fiados],
    )

    # Pasivos
    pasivos = db.query(Pasivo).all()
    add_sheet(
        "Pasivos",
        ["ID", "Acreedor", "Concepto", "Monto", "Saldo Pendiente", "Moneda",
         "Estado", "Vencimiento", "Cancelación", "Observaciones", "Creado"],
        [[
            _fmt_excel(r.id), r.acreedor, r.concepto,
            _fmt_excel(r.monto), _fmt_excel(r.saldo_pendiente), _fmt_excel(r.moneda),
            _fmt_excel(r.estado), _fmt_excel(r.fecha_vencimiento),
            _fmt_excel(r.fecha_cancelacion), r.observaciones, _fmt_excel(r.created_at),
        ] for r in pasivos],
    )

    # Gastos Operativos
    gastos = db.query(GastoOperativo).all()
    add_sheet(
        "Gastos Operativos",
        ["ID", "Concepto", "Monto", "Moneda", "Fecha Operación",
         "Hora Operación", "Observaciones", "Creado"],
        [[
            _fmt_excel(r.id), r.concepto, _fmt_excel(r.monto), _fmt_excel(r.moneda),
            _fmt_excel(r.fecha_operacion), _fmt_excel(r.hora_operacion),
            r.observaciones, _fmt_excel(r.created_at),
        ] for r in gastos],
    )

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
