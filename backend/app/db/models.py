"""
models.py — Modelos SQLAlchemy 2.0 para el Sistema Financiero DailyFC
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ══════════════════════════════════════════════════════════════════════
#  ENUMERACIONES
# ══════════════════════════════════════════════════════════════════════

class ChequeEstado(str, enum.Enum):
    EN_CARTERA = "EN_CARTERA"
    VENDIDO    = "VENDIDO"
    FIADO      = "FIADO"
    COBRADO    = "COBRADO"
    RECHAZADO  = "RECHAZADO"


class Moneda(str, enum.Enum):
    ARS = "ARS"
    USD = "USD"


class PrestamoEstado(str, enum.Enum):
    ACTIVO    = "ACTIVO"
    CANCELADO = "CANCELADO"
    EN_MORA   = "EN_MORA"


class FrecuenciaCuotas(str, enum.Enum):
    DIARIA    = "DIARIA"
    SEMANAL   = "SEMANAL"
    QUINCENAL = "QUINCENAL"
    MENSUAL   = "MENSUAL"
    ANUAL     = "ANUAL"


class CuotaEstado(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    COBRADA   = "COBRADA"
    EN_MORA   = "EN_MORA"


class MovimientoEfectivoTipo(str, enum.Enum):
    COMPRA = "COMPRA"
    VENTA  = "VENTA"


class PasivoEstado(str, enum.Enum):
    PENDIENTE = "PENDIENTE"
    CANCELADA = "CANCELADA"


# ══════════════════════════════════════════════════════════════════════
#  EXCEPCIONES DE DOMINIO
# ══════════════════════════════════════════════════════════════════════

class InvalidChequeStateTransition(Exception):
    """Transición de estado no permitida por la máquina de estados del cheque."""


class ManualOperationRequired(Exception):
    """Operación manual sin operador_id o motivo válidos."""


# ══════════════════════════════════════════════════════════════════════
#  BASE DECLARATIVA
# ══════════════════════════════════════════════════════════════════════

class Base(DeclarativeBase):
    pass


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Cliente
# ══════════════════════════════════════════════════════════════════════

class Cliente(Base):
    __tablename__ = "clientes"
    __table_args__ = (
        sa.UniqueConstraint("cuit", name="uq_clientes_cuit"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre:   Mapped[str]        = mapped_column(sa.String(160), index=True)
    cuit:     Mapped[str | None] = mapped_column(sa.String(20),  nullable=True)
    telefono: Mapped[str | None] = mapped_column(sa.String(40),  nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )

    cheques_origen:  Mapped[list[Cheque]] = relationship(
        "Cheque",
        foreign_keys="[Cheque.cliente_origen_id]",
        back_populates="cliente_origen",
    )
    cheques_destino: Mapped[list[Cheque]] = relationship(
        "Cheque",
        foreign_keys="[Cheque.cliente_destino_id]",
        back_populates="cliente_destino",
    )
    prestamos:   Mapped[list[Prestamo]]          = relationship("Prestamo",          back_populates="cliente")
    movimientos: Mapped[list[MovimientoEfectivo]] = relationship("MovimientoEfectivo", back_populates="cliente")


# ══════════════════════════════════════════════════════════════════════
#  MÁQUINA DE ESTADOS — tabla de transiciones del cheque
# ══════════════════════════════════════════════════════════════════════

_ESTADOS_TERMINALES: frozenset[ChequeEstado] = frozenset({
    ChequeEstado.VENDIDO,
    ChequeEstado.FIADO,
    ChequeEstado.COBRADO,
    ChequeEstado.RECHAZADO,
})

_TRANSICIONES: dict[ChequeEstado, frozenset[ChequeEstado]] = {
    ChequeEstado.EN_CARTERA: frozenset({
        ChequeEstado.VENDIDO,
        ChequeEstado.FIADO,
        ChequeEstado.COBRADO,
        ChequeEstado.RECHAZADO,
    }),
}


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Cheque (con máquina de estados integrada)
# ══════════════════════════════════════════════════════════════════════

class Cheque(Base):
    __tablename__ = "cheques"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",                             name="ck_cheques_monto_positive"),
        sa.CheckConstraint("porcentaje_compra >= 0 AND porcentaje_compra <= 100",
                           name="ck_cheques_porcentaje_compra_range"),
        sa.CheckConstraint(
            "porcentaje_venta IS NULL OR (porcentaje_venta >= 0 AND porcentaje_venta <= 100)",
            name="ck_cheques_porcentaje_venta_range",
        ),
        sa.CheckConstraint(
            "fecha_pago IS NULL OR fecha_emision IS NULL OR fecha_pago >= fecha_emision",
            name="ck_cheques_fecha_pago_after_emision",
        ),
    )

    nro_cheque:        Mapped[str]           = mapped_column(sa.String(64), primary_key=True)
    monto:             Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    fecha_emision:     Mapped[date | None]    = mapped_column(sa.Date(),        nullable=True)
    fecha_pago:        Mapped[date | None]    = mapped_column(sa.Date(),        nullable=True)
    porcentaje_compra: Mapped[Decimal]        = mapped_column(sa.Numeric(7, 4))
    porcentaje_venta:  Mapped[Decimal | None] = mapped_column(sa.Numeric(7, 4), nullable=True)
    ganancia:          Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    estado:            Mapped[ChequeEstado]   = mapped_column(
        sa.Enum(ChequeEstado, name="cheque_estado", create_type=False), index=True
    )
    ultimo_evento_manual_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ultimo_operador_id:      Mapped[str | None]      = mapped_column(sa.String(80), nullable=True)
    ultimo_motivo_manual:    Mapped[str | None]      = mapped_column(sa.Text(),     nullable=True)

    cliente_origen_id:  Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    cliente_destino_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True, index=True,
    )
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    cliente_origen:  Mapped[Cliente | None] = relationship(
        "Cliente", foreign_keys=[cliente_origen_id],  back_populates="cheques_origen"
    )
    cliente_destino: Mapped[Cliente | None] = relationship(
        "Cliente", foreign_keys=[cliente_destino_id], back_populates="cheques_destino"
    )
    prestamo_originado: Mapped[Prestamo | None] = relationship(
        "Prestamo", back_populates="cheque_origen", uselist=False
    )

    def transition_to(
        self,
        target: ChequeEstado,
        *,
        operador_id: str,
        motivo: str,
        porcentaje_venta: Decimal | None = None,
        cliente_destino_id: uuid.UUID | None = None,
    ) -> None:
        if not (operador_id and operador_id.strip()):
            raise ManualOperationRequired(
                "operador_id no puede estar vacío en una operación manual."
            )
        if not (motivo and motivo.strip()):
            raise ManualOperationRequired(
                "motivo no puede estar vacío en una operación manual."
            )

        if self.estado in _ESTADOS_TERMINALES:
            raise InvalidChequeStateTransition(
                f"El cheque '{self.nro_cheque}' ya está en estado terminal "
                f"'{self.estado.value}' y no admite más cambios."
            )

        destinos_validos = _TRANSICIONES.get(self.estado, frozenset())
        if target not in destinos_validos:
            raise InvalidChequeStateTransition(
                f"Transición '{self.estado.value}' → '{target.value}' no está permitida."
            )

        if target == ChequeEstado.VENDIDO:
            if porcentaje_venta is None:
                raise ManualOperationRequired(
                    "Se requiere porcentaje_venta para registrar la venta del cheque."
                )
            self.porcentaje_venta = porcentaje_venta
            self.ganancia = (
                self.monto * (porcentaje_venta - self.porcentaje_compra) / Decimal("100")
            ).quantize(Decimal("0.01"))

        if target == ChequeEstado.FIADO and cliente_destino_id is not None:
            self.cliente_destino_id = cliente_destino_id

        self.estado                  = target
        self.ultimo_operador_id      = operador_id
        self.ultimo_motivo_manual    = motivo
        self.ultimo_evento_manual_at = datetime.now(tz=UTC)


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Prestamo
# ══════════════════════════════════════════════════════════════════════

class Prestamo(Base):
    __tablename__ = "prestamos"
    __table_args__ = (
        sa.CheckConstraint("credito > 0",               name="ck_prestamos_credito_positive"),
        sa.CheckConstraint("cuotas > 0",                name="ck_prestamos_cuotas_positive"),
        sa.CheckConstraint("total_a_cobrar >= credito", name="ck_prestamos_total_a_cobrar_gte_credito"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
        index=True,
    )
    cheque_origen_nro: Mapped[str | None] = mapped_column(
        sa.String(64),
        sa.ForeignKey("cheques.nro_cheque", ondelete="SET NULL"),
        nullable=True,
    )

    credito:        Mapped[Decimal]          = mapped_column(sa.Numeric(18, 2))
    moneda:         Mapped[Moneda]           = mapped_column(sa.Enum(Moneda,           name="moneda",           create_type=False))
    cuotas:         Mapped[int]              = mapped_column(sa.Integer())
    frecuencia:     Mapped[FrecuenciaCuotas] = mapped_column(sa.Enum(FrecuenciaCuotas, name="frecuencia_cuotas", create_type=False))
    total_a_cobrar: Mapped[Decimal]          = mapped_column(sa.Numeric(18, 2))
    ganancia:       Mapped[Decimal]          = mapped_column(sa.Numeric(18, 2))
    estado:         Mapped[PrestamoEstado]   = mapped_column(
        sa.Enum(PrestamoEstado, name="prestamo_estado", create_type=False),
        default=PrestamoEstado.ACTIVO, index=True,
    )
    fecha_inicio: Mapped[date] = mapped_column(sa.Date())

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    cliente:        Mapped[Cliente]       = relationship("Cliente", back_populates="prestamos")
    cheque_origen:  Mapped[Cheque | None] = relationship("Cheque",  back_populates="prestamo_originado")
    cuotas_detalle: Mapped[list[Cuota]]   = relationship(
        "Cuota",
        back_populates="prestamo",
        cascade="all, delete-orphan",
        order_by="Cuota.numero_cuota",
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Cuota
# ══════════════════════════════════════════════════════════════════════

class Cuota(Base):
    __tablename__ = "cuotas"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",        name="ck_cuotas_monto_positive"),
        sa.CheckConstraint("numero_cuota > 0", name="ck_cuotas_numero_positive"),
        sa.UniqueConstraint("prestamo_id", "numero_cuota", name="uq_cuotas_prestamo_numero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    prestamo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("prestamos.id", ondelete="CASCADE"),
        index=True,
    )
    numero_cuota:      Mapped[int]         = mapped_column(sa.Integer())
    fecha_vencimiento: Mapped[date]        = mapped_column(sa.Date(), index=True)
    monto:             Mapped[Decimal]     = mapped_column(sa.Numeric(18, 2))
    estado:            Mapped[CuotaEstado] = mapped_column(
        sa.Enum(CuotaEstado, name="cuota_estado", create_type=False),
        default=CuotaEstado.PENDIENTE, index=True,
    )
    fecha_cobro: Mapped[date | None] = mapped_column(sa.Date(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    prestamo: Mapped[Prestamo] = relationship("Prestamo", back_populates="cuotas_detalle")


# ══════════════════════════════════════════════════════════════════════
#  MODELO: MovimientoEfectivo
# ══════════════════════════════════════════════════════════════════════

class MovimientoEfectivo(Base):
    __tablename__ = "movimientos_efectivo"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",               name="ck_movimientos_efectivo_monto_positive"),
        sa.CheckConstraint("cotizacion_aplicada > 0", name="ck_movimientos_efectivo_cotizacion_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    cliente_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tipo:   Mapped[MovimientoEfectivoTipo] = mapped_column(
        sa.Enum(MovimientoEfectivoTipo, name="movimiento_efectivo_tipo", create_type=False), index=True
    )
    moneda: Mapped[Moneda] = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False), index=True
    )
    monto:               Mapped[Decimal]  = mapped_column(sa.Numeric(18, 2))
    cotizacion_aplicada: Mapped[Decimal]  = mapped_column(sa.Numeric(18, 6))
    ganancia:            Mapped[Decimal]  = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    fecha_operacion:     Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    observaciones: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    cliente: Mapped[Cliente | None] = relationship("Cliente", back_populates="movimientos")


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Pasivo (deudas del negocio con terceros)
# ══════════════════════════════════════════════════════════════════════

class Pasivo(Base):
    __tablename__ = "pasivos"
    __table_args__ = (
        sa.CheckConstraint("monto > 0", name="ck_pasivos_monto_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    acreedor:          Mapped[str]            = mapped_column(sa.String(200), nullable=False)
    concepto:          Mapped[str]            = mapped_column(sa.Text(),      nullable=False)
    monto:             Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    moneda:            Mapped[Moneda]         = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False)
    )
    estado:            Mapped[PasivoEstado]   = mapped_column(
        sa.Enum(PasivoEstado, name="pasivo_estado", create_type=False),
        default=PasivoEstado.PENDIENTE, index=True,
    )
    fecha_vencimiento: Mapped[date | None]    = mapped_column(sa.Date(), nullable=True, index=True)
    fecha_cancelacion: Mapped[date | None]    = mapped_column(sa.Date(), nullable=True)
    observaciones:     Mapped[str | None]     = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: GastoOperativo
# ══════════════════════════════════════════════════════════════════════

class GastoOperativo(Base):
    __tablename__ = "gastos_operativos"
    __table_args__ = (
        sa.CheckConstraint("monto > 0", name="ck_gastos_operativos_monto_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    concepto:        Mapped[str]      = mapped_column(sa.String(300), nullable=False)
    monto:           Mapped[Decimal]  = mapped_column(sa.Numeric(18, 2))
    moneda:          Mapped[Moneda]   = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False),
        default=Moneda.ARS,
    )
    fecha_operacion: Mapped[date]     = mapped_column(sa.Date(), index=True)
    observaciones:   Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )
