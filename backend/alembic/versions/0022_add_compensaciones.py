"""Compensación: saldar la deuda de un cliente contra una deuda del negocio

Régimen definido 2026-08-21. El negocio le debe a Y (le compró un lote de
dólares, un cheque, lo que sea) y X le debe al negocio. En vez de que X pague y
después el negocio le pague a Y, **X le transfiere directo a Y**: bajan las dos
deudas y por la caja del negocio no pasa un peso.

Hasta acá esto solo se podía cargar como dos operaciones sueltas —cobrarle a X y
pagarle a Y—, que dejan en el libro un INGRESO y un EGRESO que nunca existieron.
El neto del día da igual, pero el reporte muestra plata moviéndose que nadie
tocó; y si el operador carga solo la mitad, la caja queda descuadrada de verdad.
Esa vía sigue estando: esta es una operación más, no un reemplazo.

**Por qué una tabla y no solo los saldos.** Sin registro, dos saldos bajan sin
nada que lo explique: no hay qué mostrar en el detalle, ni cómo revertirlo.

**Por qué el detalle por renglón.** La compensación imputa FIFO de los dos lados:
sobre todo lo que el cliente debe (fiados, deudas libres y cuotas de préstamo,
§2.c) y sobre todo lo que el negocio le debe a ese acreedor —que pueden ser
varias deudas, de la más vieja a la más nueva—. Revertirla es devolver
exactamente lo que se sacó de cada uno: recalcular el reparto al revés daría
distinto apenas alguno de los dos reciba otro movimiento. Por eso cada renglón
alcanzado deja su fila con lo que se le imputó — la cuota de un préstamo y cada
pasivo del acreedor incluidos, que es donde el reparto se vuelve fino.

Revision ID: 0022
Revises: 0021
Create Date: 2026-08-21
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "compensaciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fecha", sa.Date(), nullable=False),
        # El que debía al negocio y transfirió.
        sa.Column("cliente_id", postgresql.UUID(as_uuid=True), nullable=False),
        # El acreedor del negocio que recibió la transferencia. Es texto, igual
        # que `pasivos.acreedor`: se le puede deber a alguien que no es cliente
        # del sistema. No apunta a UNA deuda porque la transferencia se reparte
        # entre todas las que se le deben, de la más vieja a la más nueva.
        sa.Column("acreedor", sa.String(200), nullable=False),
        # Contra qué moneda de las deudas con ese acreedor imputa. Misma razón
        # que `moneda_deuda` del otro lado: ARS y USD no se suman.
        sa.Column("moneda_pasivo", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        # Lo que se transfirió, en la moneda en que se transfirió. Es el hecho
        # real de la operación; de acá salen las dos imputaciones.
        sa.Column("moneda", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        # Contra qué moneda de la deuda del cliente se imputa. ARS y USD son cajas
        # distintas y no se suman: el cobro declara una (§2.c).
        sa.Column("moneda_deuda", postgresql.ENUM(name="moneda", create_type=False), nullable=False),
        # $/USD dictada por el operador; solo si alguna de las dos patas cruza
        # monedas. El sistema jamás la asume (§4).
        sa.Column("cotizacion", sa.Numeric(18, 6), nullable=True),
        # Cuánto bajó cada lado, en su propia moneda. Se guardan calculados para
        # poder mostrar la operación sin rehacer la conversión con una cotización
        # que para entonces puede ser otra.
        sa.Column("imputado_cliente", sa.Numeric(18, 2), nullable=False),
        sa.Column("imputado_pasivo", sa.Numeric(18, 2), nullable=False),
        # Si el cliente transfirió más de lo que debía, el excedente le queda a
        # favor: se crea un pasivo del negocio con él (mismo criterio que el
        # vuelto de un cheque, §5). Se guarda cuál para poder revertirlo.
        sa.Column("excedente", sa.Numeric(18, 2), nullable=False, server_default="0"),
        sa.Column("pasivo_excedente_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observaciones", sa.Text(), nullable=True),
        sa.Column("anulado_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("anulado_por", sa.String(80), nullable=True),
        sa.Column("motivo_anulacion", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_compensaciones_monto_positive"),
        sa.CheckConstraint("excedente >= 0", name="ck_compensaciones_excedente_no_negativo"),
        sa.CheckConstraint(
            "cotizacion IS NULL OR cotizacion > 0",
            name="ck_compensaciones_cotizacion_positive",
        ),
        # RESTRICT y no CASCADE: si alguien intenta borrar el cliente, que falle
        # en vez de llevarse en silencio el registro de una operación que movió
        # deudas de los dos lados.
        sa.ForeignKeyConstraint(["cliente_id"], ["clientes.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["pasivo_excedente_id"], ["pasivos.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_compensaciones_fecha", "compensaciones", ["fecha"])
    op.create_index("ix_compensaciones_cliente", "compensaciones", ["cliente_id"])
    op.create_index("ix_compensaciones_acreedor", "compensaciones", ["acreedor"])

    op.create_table(
        "compensacion_imputaciones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("compensacion_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 'fiado' | 'deuda_simple' | 'cuota' | 'pasivo'. Del préstamo se guarda la
        # CUOTA, que es donde cae la plata: devolverle el total al préstamo sin
        # saber de qué cuota salió lo repartiría distinto al revertir. Del lado
        # del acreedor va una fila por cada deuda suya que la transferencia
        # alcanzó.
        sa.Column("entidad_tipo", sa.String(30), nullable=False),
        sa.Column("entidad_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("monto", sa.Numeric(18, 2), nullable=False),
        # Si este renglón quedó saldado por la compensación. Al revertir hay que
        # reabrirlo, y saberlo evita reabrir lo que ya estaba cerrado de antes.
        sa.Column("cancelo", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("monto > 0", name="ck_compensacion_imputaciones_monto_positive"),
        sa.ForeignKeyConstraint(
            ["compensacion_id"], ["compensaciones.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_compensacion_imputaciones_compensacion",
        "compensacion_imputaciones",
        ["compensacion_id"],
    )

    op.execute(
        sa.text(
            """
            CREATE TRIGGER trg_compensaciones_updated_at
            BEFORE UPDATE ON compensaciones
            FOR EACH ROW EXECUTE FUNCTION fn_set_updated_at()
            """
        )
    )


def downgrade() -> None:
    op.execute(sa.text("DROP TRIGGER IF EXISTS trg_compensaciones_updated_at ON compensaciones"))
    op.drop_index(
        "ix_compensacion_imputaciones_compensacion",
        table_name="compensacion_imputaciones",
    )
    op.drop_table("compensacion_imputaciones")
    op.drop_index("ix_compensaciones_acreedor", table_name="compensaciones")
    op.drop_index("ix_compensaciones_cliente", table_name="compensaciones")
    op.drop_index("ix_compensaciones_fecha", table_name="compensaciones")
    op.drop_table("compensaciones")
