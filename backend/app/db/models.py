<<<<<<< HEAD
=======
"""
models.py — Modelos SQLAlchemy 2.0 para el Sistema Financiero DailyFC
=====================================================================
Cubre las 5 tablas del esquema: clientes, cheques, prestamos,
cuotas y movimientos_efectivo.

Convenciones:
  · Todos los ENUMs usan create_type=False porque la migración Alembic
    ya los creó como tipos nativos de PostgreSQL.
  · Las PKs de tipo UUID se generan en Python (uuid.uuid4) para que
    los objetos tengan id antes del INSERT (útil en tests y relaciones).
  · updated_at usa onupdate=sa.func.now() para actualizarse en cada
    flush via SQLAlchemy (además del server_default).
"""

>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
<<<<<<< HEAD
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
=======

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# ══════════════════════════════════════════════════════════════════════
#  ENUMERACIONES  —  espejo 1:1 de los ENUM nativos en PostgreSQL
# ══════════════════════════════════════════════════════════════════════

class ChequeEstado(str, enum.Enum):
    EN_CARTERA = "EN_CARTERA"
    VENDIDO    = "VENDIDO"
    FIADO      = "FIADO"
    COBRADO    = "COBRADO"
    RECHAZADO  = "RECHAZADO"
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f


class Moneda(str, enum.Enum):
    ARS = "ARS"
    USD = "USD"


<<<<<<< HEAD
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
=======
class PrestamoEstado(str, enum.Enum):
    ACTIVO    = "activo"
    CANCELADO = "cancelado"
    EN_MORA   = "en_mora"


class FrecuenciaCuotas(str, enum.Enum):
    DIARIA    = "diaria"
    SEMANAL   = "semanal"
    QUINCENAL = "quincenal"
    MENSUAL   = "mensual"
    ANUAL     = "anual"
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f


class CuotaEstado(str, enum.Enum):
    PENDIENTE = "pendiente"
<<<<<<< HEAD
    COBRADA = "cobrada"
    EN_MORA = "en_mora"


class FrecuenciaCuotas(str, enum.Enum):
    DIARIA = "diaria"
    SEMANAL = "semanal"
    QUINCENAL = "quincenal"
    MENSUAL = "mensual"
    ANUAL = "anual"
=======
    COBRADA   = "cobrada"
    EN_MORA   = "en_mora"
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f


class MovimientoEfectivoTipo(str, enum.Enum):
    COMPRA = "compra"
<<<<<<< HEAD
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
=======
    VENTA  = "venta"


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

    # Relaciones inversas (útiles para navegación desde cliente)
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
#  MÁQUINA DE ESTADOS  —  tabla de transiciones del cheque
# ══════════════════════════════════════════════════════════════════════

# Una vez en estos estados, el cheque no admite más cambios
_ESTADOS_TERMINALES: frozenset[ChequeEstado] = frozenset({
    ChequeEstado.VENDIDO,
    ChequeEstado.FIADO,
    ChequeEstado.COBRADO,
    ChequeEstado.RECHAZADO,
})

# Mapa de transiciones válidas: estado_actual → {estados_posibles}
_TRANSICIONES: dict[ChequeEstado, frozenset[ChequeEstado]] = {
    ChequeEstado.EN_CARTERA: frozenset({
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
        ChequeEstado.VENDIDO,
        ChequeEstado.FIADO,
        ChequeEstado.COBRADO,
        ChequeEstado.RECHAZADO,
<<<<<<< HEAD
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
=======
    }),
}


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Cheque  (con máquina de estados integrada)
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
    fecha_emision:     Mapped[date | None]    = mapped_column(sa.Date(),         nullable=True)
    fecha_pago:        Mapped[date | None]    = mapped_column(sa.Date(),         nullable=True)
    porcentaje_compra: Mapped[Decimal]        = mapped_column(sa.Numeric(7, 4))
    porcentaje_venta:  Mapped[Decimal | None] = mapped_column(sa.Numeric(7, 4),  nullable=True)
    # Inicia en 0 — se actualiza al momento del egreso (venta, cobro, etc.)
    ganancia:          Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    estado:            Mapped[ChequeEstado]   = mapped_column(
        sa.Enum(ChequeEstado, name="cheque_estado", create_type=False), index=True
    )
    # Auditoría de la última operación manual
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

    # Relaciones
    cliente_origen:  Mapped[Cliente | None] = relationship(
        "Cliente", foreign_keys=[cliente_origen_id],  back_populates="cheques_origen"
    )
    cliente_destino: Mapped[Cliente | None] = relationship(
        "Cliente", foreign_keys=[cliente_destino_id], back_populates="cheques_destino"
    )
    prestamo_originado: Mapped[Prestamo | None] = relationship(
        "Prestamo", back_populates="cheque_origen", uselist=False
    )

    # ── Máquina de estados ────────────────────────────────────────────
    def transition_to(
        self,
        target: ChequeEstado,
        *,
        operador_id: str,
        motivo: str,
        porcentaje_venta: Decimal | None = None,
        cliente_destino_id: uuid.UUID | None = None,
    ) -> None:
        """
        Aplica una transición de estado validando todas las reglas de negocio.

        Raises
        ------
        ManualOperationRequired
            Si ``operador_id`` o ``motivo`` están vacíos.
        InvalidChequeStateTransition
            Si la transición desde el estado actual no está permitida.
        """
        # 1. Toda operación manual requiere identificación y justificación
        if not (operador_id and operador_id.strip()):
            raise ManualOperationRequired(
                "operador_id no puede estar vacío en una operación manual."
            )
        if not (motivo and motivo.strip()):
            raise ManualOperationRequired(
                "motivo no puede estar vacío en una operación manual."
            )

        # 2. Estados terminales no admiten más transiciones
        if self.estado in _ESTADOS_TERMINALES:
            raise InvalidChequeStateTransition(
                f"El cheque '{self.nro_cheque}' ya está en estado terminal "
                f"'{self.estado.value}' y no admite más cambios."
            )

        # 3. Validar que la transición exista en el mapa
        destinos_validos = _TRANSICIONES.get(self.estado, frozenset())
        if target not in destinos_validos:
            raise InvalidChequeStateTransition(
                f"Transición '{self.estado.value}' → '{target.value}' no está permitida."
            )

        # 4. Lógica específica por estado destino
        if target == ChequeEstado.VENDIDO:
            if porcentaje_venta is None:
                raise ManualOperationRequired(
                    "Se requiere porcentaje_venta para registrar la venta del cheque."
                )
            self.porcentaje_venta = porcentaje_venta
            # Ganancia = spread entre precio de venta y precio de compra
            self.ganancia = (
                self.monto * (porcentaje_venta - self.porcentaje_compra) / Decimal("100")
            ).quantize(Decimal("0.01"))

        if target == ChequeEstado.FIADO and cliente_destino_id is not None:
            self.cliente_destino_id = cliente_destino_id

        # 5. Registrar la transición
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
        sa.CheckConstraint("credito > 0",                        name="ck_prestamos_credito_positive"),
        sa.CheckConstraint("cuotas > 0",                         name="ck_prestamos_cuotas_positive"),
        sa.CheckConstraint("total_a_cobrar >= credito",          name="ck_prestamos_total_a_cobrar_gte_credito"),
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

    credito:        Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    moneda:         Mapped[Moneda]         = mapped_column(sa.Enum(Moneda,         name="moneda",           create_type=False))
    cuotas:         Mapped[int]            = mapped_column(sa.Integer())
    frecuencia:     Mapped[FrecuenciaCuotas] = mapped_column(sa.Enum(FrecuenciaCuotas, name="frecuencia_cuotas", create_type=False))
    total_a_cobrar: Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    ganancia:       Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    estado:         Mapped[PrestamoEstado] = mapped_column(
        sa.Enum(PrestamoEstado, name="prestamo_estado", create_type=False),
        default=PrestamoEstado.ACTIVO, index=True,
    )
    fecha_inicio: Mapped[date] = mapped_column(sa.Date())

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relaciones
    cliente:       Mapped[Cliente]        = relationship("Cliente",  back_populates="prestamos")
    cheque_origen: Mapped[Cheque | None]  = relationship("Cheque",   back_populates="prestamo_originado")
    cuotas_detalle: Mapped[list[Cuota]]   = relationship(
        "Cuota",
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
        back_populates="prestamo",
        cascade="all, delete-orphan",
        order_by="Cuota.numero_cuota",
    )


<<<<<<< HEAD
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
=======
# ══════════════════════════════════════════════════════════════════════
#  MODELO: Cuota
# ══════════════════════════════════════════════════════════════════════

class Cuota(Base):
    __tablename__ = "cuotas"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",          name="ck_cuotas_monto_positive"),
        sa.CheckConstraint("numero_cuota > 0",   name="ck_cuotas_numero_positive"),
        sa.UniqueConstraint("prestamo_id", "numero_cuota", name="uq_cuotas_prestamo_numero"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    prestamo_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("prestamos.id", ondelete="CASCADE"),
        index=True,
    )
    numero_cuota:      Mapped[int]           = mapped_column(sa.Integer())
    fecha_vencimiento: Mapped[date]          = mapped_column(sa.Date(), index=True)
    monto:             Mapped[Decimal]       = mapped_column(sa.Numeric(18, 2))
    estado:            Mapped[CuotaEstado]   = mapped_column(
        sa.Enum(CuotaEstado, name="cuota_estado", create_type=False),
        default=CuotaEstado.PENDIENTE, index=True,
    )
    fecha_cobro: Mapped[date | None] = mapped_column(sa.Date(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relación
    prestamo: Mapped[Prestamo] = relationship("Prestamo", back_populates="cuotas_detalle")


# ══════════════════════════════════════════════════════════════════════
#  MODELO: MovimientoEfectivo
# ══════════════════════════════════════════════════════════════════════

class MovimientoEfectivo(Base):
    __tablename__ = "movimientos_efectivo"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",              name="ck_movimientos_efectivo_monto_positive"),
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
    monto:               Mapped[Decimal]       = mapped_column(sa.Numeric(18, 2))
    cotizacion_aplicada: Mapped[Decimal]       = mapped_column(sa.Numeric(18, 6))
    ganancia:            Mapped[Decimal]       = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    fecha_operacion:     Mapped[datetime]      = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), index=True
    )
    observaciones: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    # Relación
    cliente: Mapped[Cliente | None] = relationship("Cliente", back_populates="movimientos")
>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
