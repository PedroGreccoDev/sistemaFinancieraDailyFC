from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Moneda(str, enum.Enum):
    ARS = "ARS"
    USD = "USD"


class ChequeEstado(str, enum.Enum):
    EN_CARTERA = "EN_CARTERA"
    VENDIDO = "VENDIDO"
    FIADO = "FIADO"
    COBRADO = "COBRADO"
    RECHAZADO = "RECHAZADO"


class PrestamoEstado(str, enum.Enum):
    ACTIVO = "activo"
    CANCELADO = "cancelado"
    EN_MORA = "en_mora"


class CuotaEstado(str, enum.Enum):
    PENDIENTE = "pendiente"
    COBRADA = "cobrada"
    EN_MORA = "en_mora"


class FrecuenciaCuotas(str, enum.Enum):
    DIARIA = "diaria"
    SEMANAL = "semanal"
    QUINCENAL = "quincenal"
    MENSUAL = "mensual"
    ANUAL = "anual"


class MovimientoEfectivoTipo(str, enum.Enum):
    COMPRA = "compra"
    VENTA = "venta"


class InvalidChequeStateTransition(ValueError):
    def __init__(self, current_state: ChequeEstado, target_state: ChequeEstado) -> None:
        super().__init__(
            f"Transicion de cheque invalida: {current_state.value} -> {target_state.value}"
        )


class ManualOperationRequired(ValueError):
    def __init__(self, field_name: str) -> None:
        super().__init__(f"La operacion manual requiere el campo '{field_name}'.")


CHEQUE_TRANSITIONS: Final[dict[ChequeEstado, set[ChequeEstado]]] = {
    ChequeEstado.EN_CARTERA: {
        ChequeEstado.VENDIDO,
        ChequeEstado.FIADO,
        ChequeEstado.COBRADO,
        ChequeEstado.RECHAZADO,
    },
    ChequeEstado.FIADO: {
        ChequeEstado.COBRADO,
        ChequeEstado.RECHAZADO,
    },
    ChequeEstado.VENDIDO: set(),
    ChequeEstado.COBRADO: set(),
    ChequeEstado.RECHAZADO: set(),
}


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Cliente(TimestampMixin, Base):
    __tablename__ = "clientes"
    __table_args__ = (
        UniqueConstraint("cuit", name="uq_clientes_cuit"),
        Index("ix_clientes_nombre", "nombre"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    cuit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    telefono: Mapped[str | None] = mapped_column(String(40), nullable=True)

    cheques_recibidos: Mapped[list[Cheque]] = relationship(
        back_populates="cliente_origen",
        foreign_keys="Cheque.cliente_origen_id",
    )
    cheques_entregados: Mapped[list[Cheque]] = relationship(
        back_populates="cliente_destino",
        foreign_keys="Cheque.cliente_destino_id",
    )
    prestamos: Mapped[list[Prestamo]] = relationship(back_populates="cliente")
    movimientos_efectivo: Mapped[list[MovimientoEfectivo]] = relationship(
        back_populates="cliente"
    )


class Cheque(TimestampMixin, Base):
    __tablename__ = "cheques"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_cheques_monto_positive"),
        CheckConstraint(
            "porcentaje_compra >= 0 AND porcentaje_compra <= 100",
            name="ck_cheques_porcentaje_compra_range",
        ),
        CheckConstraint(
            "porcentaje_venta IS NULL OR "
            "(porcentaje_venta >= 0 AND porcentaje_venta <= 100)",
            name="ck_cheques_porcentaje_venta_range",
        ),
        CheckConstraint(
            "fecha_pago IS NULL OR fecha_emision IS NULL OR fecha_pago >= fecha_emision",
            name="ck_cheques_fecha_pago_after_emision",
        ),
        Index("ix_cheques_estado", "estado"),
        Index("ix_cheques_cliente_origen_id", "cliente_origen_id"),
        Index("ix_cheques_cliente_destino_id", "cliente_destino_id"),
    )

    nro_cheque: Mapped[str] = mapped_column(String(64), primary_key=True)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    fecha_emision: Mapped[date | None] = mapped_column(Date, nullable=True)
    fecha_pago: Mapped[date | None] = mapped_column(Date, nullable=True)
    porcentaje_compra: Mapped[Decimal] = mapped_column(Numeric(7, 4), nullable=False)
    porcentaje_venta: Mapped[Decimal | None] = mapped_column(
        Numeric(7, 4), nullable=True
    )
    ganancia: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    estado: Mapped[ChequeEstado] = mapped_column(
        Enum(ChequeEstado, name="cheque_estado"),
        nullable=False,
        default=ChequeEstado.EN_CARTERA,
    )
    ultimo_evento_manual_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ultimo_operador_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    ultimo_motivo_manual: Mapped[str | None] = mapped_column(Text, nullable=True)

    cliente_origen_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True,
    )
    cliente_destino_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True,
    )

    cliente_origen: Mapped[Cliente | None] = relationship(
        back_populates="cheques_recibidos",
        foreign_keys=[cliente_origen_id],
    )
    cliente_destino: Mapped[Cliente | None] = relationship(
        back_populates="cheques_entregados",
        foreign_keys=[cliente_destino_id],
    )
    prestamos_originados: Mapped[list[Prestamo]] = relationship(
        back_populates="cheque_origen"
    )

    @staticmethod
    def calcular_ganancia(
        monto: Decimal,
        porcentaje_compra: Decimal,
        porcentaje_venta: Decimal,
    ) -> Decimal:
        spread = porcentaje_venta - porcentaje_compra
        return (monto * spread / Decimal("100")).quantize(Decimal("0.01"))

    def transition_to(
        self,
        target_state: ChequeEstado,
        *,
        operador_id: str,
        motivo: str,
        occurred_at: datetime | None = None,
        porcentaje_venta: Decimal | None = None,
        cliente_destino_id: uuid.UUID | None = None,
    ) -> None:
        if not operador_id:
            raise ManualOperationRequired("operador_id")
        if not motivo:
            raise ManualOperationRequired("motivo")
        if target_state == self.estado:
            return
        if target_state not in CHEQUE_TRANSITIONS[self.estado]:
            raise InvalidChequeStateTransition(self.estado, target_state)

        if target_state == ChequeEstado.VENDIDO:
            if porcentaje_venta is None:
                raise ManualOperationRequired("porcentaje_venta")
            self.porcentaje_venta = porcentaje_venta
            self.ganancia = self.calcular_ganancia(
                self.monto,
                self.porcentaje_compra,
                porcentaje_venta,
            )

        if target_state in {ChequeEstado.VENDIDO, ChequeEstado.FIADO}:
            self.cliente_destino_id = cliente_destino_id

        self.estado = target_state
        self.ultimo_operador_id = operador_id
        self.ultimo_motivo_manual = motivo
        self.ultimo_evento_manual_at = occurred_at or datetime.now(UTC)


class Prestamo(TimestampMixin, Base):
    __tablename__ = "prestamos"
    __table_args__ = (
        CheckConstraint("credito > 0", name="ck_prestamos_credito_positive"),
        CheckConstraint("cuotas > 0", name="ck_prestamos_cuotas_positive"),
        CheckConstraint(
            "total_a_cobrar >= credito",
            name="ck_prestamos_total_a_cobrar_gte_credito",
        ),
        Index("ix_prestamos_cliente_id", "cliente_id"),
        Index("ix_prestamos_estado", "estado"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clientes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    cheque_origen_nro: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("cheques.nro_cheque", ondelete="SET NULL"),
        nullable=True,
    )
    credito: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    moneda: Mapped[Moneda] = mapped_column(Enum(Moneda, name="moneda"), nullable=False)
    cuotas: Mapped[int] = mapped_column(Integer, nullable=False)
    frecuencia: Mapped[FrecuenciaCuotas] = mapped_column(
        Enum(FrecuenciaCuotas, name="frecuencia_cuotas"),
        nullable=False,
    )
    total_a_cobrar: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    ganancia: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[PrestamoEstado] = mapped_column(
        Enum(PrestamoEstado, name="prestamo_estado"),
        nullable=False,
        default=PrestamoEstado.ACTIVO,
    )
    fecha_inicio: Mapped[date] = mapped_column(Date, nullable=False, default=date.today)

    cliente: Mapped[Cliente] = relationship(back_populates="prestamos")
    cheque_origen: Mapped[Cheque | None] = relationship(
        back_populates="prestamos_originados"
    )
    cuotas_detalle: Mapped[list[Cuota]] = relationship(
        back_populates="prestamo",
        cascade="all, delete-orphan",
        order_by="Cuota.numero_cuota",
    )


class Cuota(TimestampMixin, Base):
    __tablename__ = "cuotas"
    __table_args__ = (
        UniqueConstraint("prestamo_id", "numero_cuota", name="uq_cuotas_prestamo_numero"),
        CheckConstraint("numero_cuota > 0", name="ck_cuotas_numero_positive"),
        CheckConstraint("monto > 0", name="ck_cuotas_monto_positive"),
        Index("ix_cuotas_prestamo_id", "prestamo_id"),
        Index("ix_cuotas_estado", "estado"),
        Index("ix_cuotas_fecha_vencimiento", "fecha_vencimiento"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    prestamo_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("prestamos.id", ondelete="CASCADE"),
        nullable=False,
    )
    numero_cuota: Mapped[int] = mapped_column(Integer, nullable=False)
    fecha_vencimiento: Mapped[date] = mapped_column(Date, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    estado: Mapped[CuotaEstado] = mapped_column(
        Enum(CuotaEstado, name="cuota_estado"),
        nullable=False,
        default=CuotaEstado.PENDIENTE,
    )
    fecha_cobro: Mapped[date | None] = mapped_column(Date, nullable=True)

    prestamo: Mapped[Prestamo] = relationship(back_populates="cuotas_detalle")


class MovimientoEfectivo(TimestampMixin, Base):
    __tablename__ = "movimientos_efectivo"
    __table_args__ = (
        CheckConstraint("monto > 0", name="ck_movimientos_efectivo_monto_positive"),
        CheckConstraint(
            "cotizacion_aplicada > 0",
            name="ck_movimientos_efectivo_cotizacion_positive",
        ),
        Index("ix_movimientos_efectivo_tipo", "tipo"),
        Index("ix_movimientos_efectivo_moneda", "moneda"),
        Index("ix_movimientos_efectivo_fecha_operacion", "fecha_operacion"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    cliente_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clientes.id", ondelete="SET NULL"),
        nullable=True,
    )
    tipo: Mapped[MovimientoEfectivoTipo] = mapped_column(
        Enum(MovimientoEfectivoTipo, name="movimiento_efectivo_tipo"),
        nullable=False,
    )
    moneda: Mapped[Moneda] = mapped_column(Enum(Moneda, name="moneda"), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    cotizacion_aplicada: Mapped[Decimal] = mapped_column(Numeric(18, 6), nullable=False)
    ganancia: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0.00")
    )
    fecha_operacion: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    observaciones: Mapped[str | None] = mapped_column(Text, nullable=True)

    cliente: Mapped[Cliente | None] = relationship(back_populates="movimientos_efectivo")
