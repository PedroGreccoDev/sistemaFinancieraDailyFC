"""
models.py — Modelos SQLAlchemy 2.0 para el Sistema Financiero DailyFC
"""

from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime, time
from decimal import Decimal

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, column_property, mapped_column, relationship


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


class FiadoEstado(str, enum.Enum):
    ABIERTO   = "ABIERTO"
    CANCELADO = "CANCELADO"


class DeudaSimpleEstado(str, enum.Enum):
    ABIERTA   = "ABIERTA"
    CANCELADA = "CANCELADA"


class CajaTipo(str, enum.Enum):
    INGRESO = "INGRESO"
    EGRESO  = "EGRESO"


class MedioPago(str, enum.Enum):
    EFECTIVO      = "EFECTIVO"
    TRANSFERENCIA = "TRANSFERENCIA"


class CajaCategoria(str, enum.Enum):
    COBRO_CUOTA          = "COBRO_CUOTA"
    COBRO_FIADO          = "COBRO_FIADO"
    VENTA_CHEQUE         = "VENTA_CHEQUE"
    COBRO_CHEQUE         = "COBRO_CHEQUE"
    COMPRA_CHEQUE        = "COMPRA_CHEQUE"
    COMPRA_USD           = "COMPRA_USD"
    VENTA_USD            = "VENTA_USD"
    OTORGAMIENTO_PRESTAMO = "OTORGAMIENTO_PRESTAMO"
    GASTO                = "GASTO"
    PAGO_PASIVO          = "PAGO_PASIVO"
    VUELTO_PASIVO        = "VUELTO_PASIVO"
    OTORGAMIENTO_DEUDA   = "OTORGAMIENTO_DEUDA"
    COBRO_DEUDA          = "COBRO_DEUDA"
    # Efectivo que ya estaba en el cajón al poner el sistema en marcha. No es un
    # ingreso del día: el reporte lo trata como saldo de apertura (§Apertura).
    SALDO_INICIAL        = "SALDO_INICIAL"
    # Plata agregada o restada a mano, sin operación de negocio detrás: corrección
    # de un descuadre, aporte o retiro del dueño (§Ajustes de caja).
    AJUSTE_CAJA          = "AJUSTE_CAJA"


class AjusteCajaMotivo(str, enum.Enum):
    """Por qué se tocó la caja a mano. Se elige al cargar el ajuste."""

    # El sistema no coincide con el efectivo real del cajón y se emparejan.
    CORRECCION = "CORRECCION"
    # El dueño puso plata en el negocio.
    APORTE     = "APORTE"
    # El dueño sacó plata del negocio.
    RETIRO     = "RETIRO"
    # Cualquier otra razón; exige descripción.
    OTRO       = "OTRO"


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
#  MIXIN: Anulable (borrado lógico) — régimen definido 2026-08-06
# ══════════════════════════════════════════════════════════════════════

class AnulableMixin:
    """Marca de anulación para las entidades que el panel puede "eliminar".

    Eliminar NO borra la fila: la anula. El registro conserva su historia —para
    poder auditar después por qué la caja dio distinto— pero sale de los listados
    y sus líneas de caja se revierten.

    Es **ortogonal al estado** de cada entidad: un cheque anulado conserva su
    `estado` histórico. No hay valor ANULADO en los enums de estado, que rompería
    la máquina de estados del cheque y los reportes.
    """

    anulado_at:       Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    anulado_por:      Mapped[str | None]      = mapped_column(sa.String(80), nullable=True)
    motivo_anulacion: Mapped[str | None]      = mapped_column(sa.Text(),     nullable=True)

    @property
    def anulado(self) -> bool:
        return self.anulado_at is not None


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
    prestamos:      Mapped[list[Prestamo]]          = relationship("Prestamo",          back_populates="cliente")
    movimientos:    Mapped[list[MovimientoEfectivo]] = relationship("MovimientoEfectivo", back_populates="cliente")
    fiados:         Mapped[list[Fiado]]              = relationship("Fiado",              back_populates="cliente")
    deudas_simples: Mapped[list[DeudaSimple]]        = relationship("DeudaSimple",        back_populates="cliente")


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

class Cheque(AnulableMixin, Base):
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
        # El número de cheque NO es único globalmente: solo lo es dentro de un mismo
        # banco. Dos cheques de bancos distintos pueden compartir número. Por eso la
        # identidad es la PK subrogada `id` y la unicidad es (banco, nro_cheque).
        # Nota: en Postgres NULL es distinto de NULL, así que cheques sin banco
        # detectado no chocan entre sí (se permiten cargar igual).
        # La unicidad es un índice ÚNICO PARCIAL sobre los cheques vivos
        # (migración 0017): un cheque anulado libera su número para que se pueda
        # volver a cargar corregido con el mismo (banco, nro).
        sa.Index(
            "uq_cheques_banco_nro_vivos",
            "banco", "nro_cheque",
            unique=True,
            postgresql_where=sa.text("anulado_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    nro_cheque:        Mapped[str]           = mapped_column(sa.String(64), nullable=False, index=True)
    banco:             Mapped[str | None]    = mapped_column(sa.String(120), nullable=True)
    monto:             Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    fecha_emision:     Mapped[date | None]    = mapped_column(sa.Date(),        nullable=True)
    fecha_pago:        Mapped[date | None]    = mapped_column(sa.Date(),        nullable=True)
    porcentaje_compra: Mapped[Decimal]        = mapped_column(sa.Numeric(7, 4))
    # Pesos realmente abonados al comprarlo. NULL = se pagó todo (el caso normal).
    # Lo que falte para el valor neto quedó a deber y vive como pasivo con el
    # vendedor (§Comprar sin abonar). Se guarda porque el egreso de caja se
    # reconstruye desde acá al editar: derivarlo del saldo del pasivo daría mal
    # apenas ese pasivo reciba un pago.
    monto_abonado:     Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    porcentaje_venta:  Mapped[Decimal | None] = mapped_column(sa.Numeric(7, 4), nullable=True)
    ganancia:          Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    estado:            Mapped[ChequeEstado]   = mapped_column(
        sa.Enum(ChequeEstado, name="cheque_estado", create_type=False), index=True
    )
    ultimo_evento_manual_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
    ultimo_operador_id:      Mapped[str | None]      = mapped_column(sa.String(80), nullable=True)
    ultimo_motivo_manual:    Mapped[str | None]      = mapped_column(sa.Text(),     nullable=True)

    # Cheque que YA estaba en cartera al arrancar el sistema (comprado antes de
    # que existiera). Es inventario de apertura: no asienta el egreso de compra,
    # porque esa plata salió fuera del período que la caja cubre —y el efectivo
    # inicial ya la tiene descontada—. Migración 0018.
    es_carga_inicial: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false(), default=False
    )

    # Foto del cheque (cargado por WhatsApp/OCR). Diferida: los listados nunca
    # cargan los bytes; solo se leen vía GET /cheques/{nro}/foto.
    foto:      Mapped[bytes | None] = mapped_column(sa.LargeBinary(), nullable=True, deferred=True)
    foto_mime: Mapped[str | None]   = mapped_column(sa.String(64),    nullable=True)
    # Expresión SQL barata: indica si hay foto sin traer los bytes a memoria.
    tiene_foto = column_property(
        sa.literal_column("(cheques.foto IS NOT NULL)", type_=sa.Boolean())
    )

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
    fiado_originado: Mapped[Fiado | None] = relationship(
        "Fiado", back_populates="cheque", uselist=False
    )

    def transition_to(
        self,
        target: ChequeEstado,
        *,
        operador_id: str,
        motivo: str,
        porcentaje_venta: Decimal | None = None,
        cliente_destino_id: uuid.UUID | None = None,
        event_at: datetime | None = None,
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
                self.monto * (self.porcentaje_compra - porcentaje_venta) / Decimal("100")
            ).quantize(Decimal("0.01"))

        if target == ChequeEstado.FIADO:
            if porcentaje_venta is None:
                raise ManualOperationRequired(
                    "Se requiere porcentaje_venta para registrar el fiado del cheque."
                )
            self.porcentaje_venta = porcentaje_venta
            if cliente_destino_id is not None:
                self.cliente_destino_id = cliente_destino_id

        self.estado                  = target
        self.ultimo_operador_id      = operador_id
        self.ultimo_motivo_manual    = motivo
        self.ultimo_evento_manual_at = event_at or datetime.now(tz=UTC)


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Prestamo
# ══════════════════════════════════════════════════════════════════════

class Prestamo(AnulableMixin, Base):
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
        sa.CheckConstraint(
            "monto_pagado >= 0 AND monto_pagado <= monto",
            name="ck_cuotas_monto_pagado_range",
        ),
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
    # Cuánto de la cuota ya se cobró. La cuota es COBRADA solo cuando iguala a `monto`;
    # el saldo pendiente de la cuota es `monto - monto_pagado`. Permite pagos parciales
    # de importe libre imputados a nivel préstamo (ver svc_prestamos.pagar_prestamo).
    monto_pagado:      Mapped[Decimal]     = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
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

class MovimientoEfectivo(AnulableMixin, Base):
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
    # Pesos realmente abonados en una COMPRA. NULL = se pagó todo (el caso normal).
    # Lo que falte para `monto × cotizacion` quedó a deber y vive como pasivo con
    # el vendedor (§Comprar sin abonar). Se guarda porque el egreso de caja se
    # reconstruye desde acá al editar.
    monto_abonado:       Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    ganancia:            Mapped[Decimal]  = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    # Stock de USD aún no consumido de esta operación. Solo aplica a las COMPRA:
    # arranca = monto y se decrementa al imputar ventas FIFO (las VENTA quedan en 0).
    usd_restante:        Mapped[Decimal]  = mapped_column(sa.Numeric(18, 2), default=Decimal("0.00"))
    # Lote de dólares que YA se tenían al arrancar el sistema (migración 0019).
    # Aporta stock para poder vender, con su costo promedio, pero NO asienta caja:
    # esos pesos salieron antes de que el sistema existiera. Ver §Apertura.
    es_apertura:         Mapped[bool]     = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false(), default=False
    )
    # Lote creado por un ajuste manual de caja que sumó dólares (migración 0020).
    # Aporta stock igual que una compra, pero NO asienta caja: la línea del propio
    # ajuste ya movió la caja USD. Tampoco es una operación de divisas, así que
    # queda fuera del listado de Divisas. Ver §Ajustes de caja.
    es_ajuste:           Mapped[bool]     = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.false(), default=False
    )
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
#  MODELO: Fiado (deuda de cliente por cheque entregado en crédito)
# ══════════════════════════════════════════════════════════════════════

class Fiado(AnulableMixin, Base):
    __tablename__ = "fiados"
    __table_args__ = (
        sa.CheckConstraint("monto_original > 0",   name="ck_fiados_monto_positive"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_fiados_saldo_non_negative"),
        sa.CheckConstraint(
            "porcentaje_venta >= 0 AND porcentaje_venta <= 100",
            name="ck_fiados_porcentaje_range",
        ),
        # Un cheque origina un solo fiado, pero solo entre los fiados vivos: si el
        # fiado se anula, el cheque vuelve a poder fiarse (migración 0017).
        sa.Index(
            "uq_fiados_cheque_vivos",
            "cheque_id",
            unique=True,
            postgresql_where=sa.text("anulado_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    cheque_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("cheques.id", ondelete="RESTRICT"),
        index=True,
    )
    cliente_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
        index=True,
    )

    monto_original:   Mapped[Decimal]     = mapped_column(sa.Numeric(18, 2))
    porcentaje_venta: Mapped[Decimal]     = mapped_column(sa.Numeric(7, 4))
    saldo_pendiente:  Mapped[Decimal]     = mapped_column(sa.Numeric(18, 2))
    estado:           Mapped[FiadoEstado] = mapped_column(
        sa.Enum(FiadoEstado, name="fiado_estado", create_type=False),
        default=FiadoEstado.ABIERTO, index=True,
    )
    fecha_fiado: Mapped[date] = mapped_column(sa.Date())

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    cheque:  Mapped[Cheque]  = relationship("Cheque",  back_populates="fiado_originado")
    cliente: Mapped[Cliente] = relationship("Cliente", back_populates="fiados")

    @property
    def cheque_nro(self) -> str | None:
        """Número del cheque originante. Atajo de lectura sobre la relación, para
        seguir exponiendo `cheque_nro` en la API y el bot sin guardarlo duplicado."""
        return self.cheque.nro_cheque if self.cheque else None


# ══════════════════════════════════════════════════════════════════════
#  MODELO: DeudaSimple (deuda libre de un cliente — sin cuotas ni cheque)
# ══════════════════════════════════════════════════════════════════════

class DeudaSimple(AnulableMixin, Base):
    """Cuenta por cobrar de un cliente que no es un préstamo con cuotas ni un
    fiado de cheque: una deuda libre con su razón (concepto), monto, moneda y
    fecha. Al registrarla sale un EGRESO de caja (se entregó la plata) y al
    cobrarla entra un INGRESO (total o parcial, admite cross-currency). Pasa a
    CANCELADA cuando el saldo llega a 0."""

    __tablename__ = "deudas_simples"
    __table_args__ = (
        sa.CheckConstraint("monto > 0",           name="ck_deudas_simples_monto_positive"),
        sa.CheckConstraint("saldo_pendiente >= 0", name="ck_deudas_simples_saldo_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    cliente_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("clientes.id", ondelete="RESTRICT"),
        index=True,
    )

    concepto:        Mapped[str]               = mapped_column(sa.Text(), nullable=False)
    monto:           Mapped[Decimal]           = mapped_column(sa.Numeric(18, 2))
    saldo_pendiente: Mapped[Decimal]           = mapped_column(sa.Numeric(18, 2))
    moneda:          Mapped[Moneda]            = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False)
    )
    estado:          Mapped[DeudaSimpleEstado] = mapped_column(
        sa.Enum(DeudaSimpleEstado, name="deuda_simple_estado", create_type=False),
        default=DeudaSimpleEstado.ABIERTA, index=True,
    )
    fecha:             Mapped[date]            = mapped_column(sa.Date())
    fecha_cancelacion: Mapped[date | None]     = mapped_column(sa.Date(), nullable=True)
    observaciones:     Mapped[str | None]      = mapped_column(sa.Text(), nullable=True)
    # Cotización ($/USD) de la PRIMERA cobranza en moneda distinta a la deuda.
    # Se setea una sola vez y sirve de default editable para los cobros siguientes.
    cotizacion_pago:   Mapped[Decimal | None]  = mapped_column(sa.Numeric(18, 4), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    cliente: Mapped[Cliente] = relationship("Cliente", back_populates="deudas_simples")


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Pasivo (deudas del negocio con terceros)
# ══════════════════════════════════════════════════════════════════════

class Pasivo(AnulableMixin, Base):
    __tablename__ = "pasivos"
    __table_args__ = (
        sa.CheckConstraint("monto > 0", name="ck_pasivos_monto_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    acreedor:          Mapped[str]            = mapped_column(sa.String(200), nullable=False)
    concepto:          Mapped[str]            = mapped_column(sa.Text(),      nullable=False)
    monto:             Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
    saldo_pendiente:   Mapped[Decimal]        = mapped_column(sa.Numeric(18, 2))
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
    # Cotización ($/USD) de la PRIMERA cancelación en moneda distinta a la deuda.
    # Se setea una sola vez y sirve de default editable para los pagos siguientes.
    cotizacion_pago:   Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 4), nullable=True)

    # De qué compra salió este pasivo: 'movimiento_efectivo' (dólares comprados a
    # deber) o 'cheque' (cheque comprado a deber). NULL = cargado a mano.
    # Sin este vínculo, anular la compra dejaría vivo un pasivo por plata que ya
    # no se debe (§Comprar sin abonar).
    origen_tipo:       Mapped[str | None]     = mapped_column(sa.String(40), nullable=True)
    origen_id:         Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: GastoOperativo
# ══════════════════════════════════════════════════════════════════════

class GastoOperativo(AnulableMixin, Base):
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
    hora_operacion:  Mapped[time | None] = mapped_column(sa.Time(), nullable=True)
    observaciones:   Mapped[str | None] = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: MovimientoCaja  (libro de caja — flujo real de ingresos/egresos)
# ══════════════════════════════════════════════════════════════════════

class MovimientoCaja(Base):
    """Cada fila es un movimiento de efectivo real (entra o sale plata).

    Es la fuente única del reporte de caja diaria. Lo escriben los servicios en
    el call site de cada operación (no la máquina de estados del cheque), porque
    el significado de caja depende del contexto. `fecha` es el día local (ART)
    del evento; el reporte filtra por día directo, sin conversión de zona horaria.
    """

    __tablename__ = "movimientos_caja"
    __table_args__ = (
        sa.CheckConstraint("monto > 0", name="ck_movimientos_caja_monto_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    fecha:     Mapped[date]          = mapped_column(sa.Date(), index=True)
    moneda:    Mapped[Moneda]        = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False), index=True
    )
    tipo:      Mapped[CajaTipo]      = mapped_column(
        sa.Enum(CajaTipo, name="caja_tipo", create_type=False), index=True
    )
    categoria: Mapped[CajaCategoria] = mapped_column(
        sa.Enum(CajaCategoria, name="caja_categoria", create_type=False), index=True
    )
    monto:     Mapped[Decimal]       = mapped_column(sa.Numeric(18, 2))
    # Solo VENTA_USD: ganancia FIFO realizada (en ARS). Dato de reporte, no de caja.
    ganancia:  Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    # Solo pagos de pasivo (PAGO_PASIVO): medio con el que se pagó. Null en el resto.
    medio_pago: Mapped[MedioPago | None] = mapped_column(
        sa.Enum(MedioPago, name="medio_pago", create_type=False), nullable=True
    )
    # $/USD aplicado cuando un pago cruza monedas (deuda en una moneda, pago en otra).
    # Null cuando pago y deuda comparten moneda. Solo dato de reporte/auditoría.
    cotizacion: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 4), nullable=True)

    # Enlace flojo a la entidad origen (cheque/prestamo/cuota/fiado/pasivo/gasto/movimiento).
    referencia_tipo: Mapped[str | None]       = mapped_column(sa.String(40), nullable=True)
    referencia_id:   Mapped[uuid.UUID | None] = mapped_column(PG_UUID(as_uuid=True), nullable=True, index=True)
    detalle:         Mapped[str | None]       = mapped_column(sa.Text(), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: AjusteCaja  (agregar o restar efectivo a mano)
# ══════════════════════════════════════════════════════════════════════

class AjusteCaja(AnulableMixin, Base):
    """Plata que entra o sale de la caja sin una operación de negocio detrás.

    Corrige un descuadre contra el efectivo real del cajón, o registra que el
    dueño puso o sacó plata. Asienta una línea `AJUSTE_CAJA` en el libro con el
    `tipo` que le corresponde, así que cuenta como ingreso/egreso del período.

    Es una entidad propia y no una línea suelta del libro para poder auditar
    **por qué** se tocó la caja y anularla con el motor común (§Anulación).
    """

    __tablename__ = "ajustes_caja"
    __table_args__ = (
        sa.CheckConstraint("monto > 0", name="ck_ajustes_caja_monto_positive"),
        sa.CheckConstraint(
            "cotizacion_usd IS NULL OR cotizacion_usd > 0",
            name="ck_ajustes_caja_cotizacion_positive",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    fecha:  Mapped[date]   = mapped_column(sa.Date(), index=True)
    moneda: Mapped[Moneda] = mapped_column(
        sa.Enum(Moneda, name="moneda", create_type=False), index=True
    )
    # INGRESO suma efectivo, EGRESO lo resta. `monto` siempre positivo.
    tipo:   Mapped[CajaTipo] = mapped_column(
        sa.Enum(CajaTipo, name="caja_tipo", create_type=False)
    )
    motivo: Mapped[AjusteCajaMotivo] = mapped_column(
        sa.Enum(AjusteCajaMotivo, name="ajuste_caja_motivo", create_type=False)
    )
    monto:  Mapped[Decimal] = mapped_column(sa.Numeric(18, 2))
    # Solo cuando el ajuste SUMA USD: costo ($/USD) del lote FIFO que crea, para
    # que esos dólares se puedan vender después con su ganancia bien calculada.
    cotizacion_usd: Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 6), nullable=True)
    # Lote creado por este ajuste, si sumó dólares. Se borra al anularlo.
    lote_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        sa.ForeignKey("movimientos_efectivo.id", ondelete="SET NULL"),
        nullable=True,
    )
    descripcion: Mapped[str | None] = mapped_column(sa.Text(), nullable=True)
    operador_id: Mapped[str]        = mapped_column(sa.String(80))

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Usuario  (cuentas de acceso al panel)
# ══════════════════════════════════════════════════════════════════════

class Usuario(Base):
    __tablename__ = "usuarios"
    __table_args__ = (
        sa.UniqueConstraint("username", name="uq_usuarios_username"),
    )

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Se guarda SIEMPRE en minúsculas (la unicidad es case-insensitive de facto).
    username:      Mapped[str]        = mapped_column(sa.String(80), nullable=False)
    password_hash: Mapped[str]        = mapped_column(sa.String(255), nullable=False)
    # Teléfono (solo dígitos, sin @c.us): destino del código de recuperación por WhatsApp.
    phone:         Mapped[str | None] = mapped_column(sa.String(40), nullable=True)

    is_admin: Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, server_default=sa.text("false"))
    activo:   Mapped[bool] = mapped_column(sa.Boolean(), nullable=False, server_default=sa.text("true"))
    # Se incrementa al resetear/recuperar la clave → invalida los tokens viejos.
    token_version: Mapped[int] = mapped_column(sa.Integer(), nullable=False, server_default=sa.text("0"))
    # True cuando la clave la fijó otro (alta con temporal o reset del admin): al
    # ingresar, el usuario queda obligado a definir su propia clave antes de operar.
    must_change_password: Mapped[bool] = mapped_column(
        sa.Boolean(), nullable=False, server_default=sa.text("false")
    )

    # Código de recuperación vigente (hash + vencimiento corto).
    reset_code_hash:       Mapped[str | None]      = mapped_column(sa.String(255), nullable=True)
    reset_code_expires_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: Invitacion  (alta de usuarios por enlace de un solo uso)
# ══════════════════════════════════════════════════════════════════════

class Invitacion(Base):
    __tablename__ = "invitaciones"

    id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # Teléfono al que se envió la invitación por WhatsApp (queda como phone del usuario resultante).
    phone:    Mapped[str | None] = mapped_column(sa.String(40), nullable=True)
    is_admin: Mapped[bool]       = mapped_column(sa.Boolean(), nullable=False, server_default=sa.text("false"))

    # Hash del token que viaja en el enlace (el token en claro no se persiste).
    token_hash: Mapped[str]            = mapped_column(sa.String(255), nullable=False)
    expires_at: Mapped[datetime]       = mapped_column(sa.DateTime(timezone=True), nullable=False)
    used_at:    Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )


# ══════════════════════════════════════════════════════════════════════
#  MODELO: ConfiguracionApertura  (arranque del sistema — migración 0018)
# ══════════════════════════════════════════════════════════════════════

class ConfiguracionApertura(Base):
    """Los saldos con los que el negocio arrancó a usar el sistema.

    Cuando el sistema se puso en marcha el negocio ya venía funcionando: había
    efectivo en el cajón y cheques en cartera comprados tiempo atrás. Los dos son
    **saldos de apertura**, no operaciones del día, y esta tabla los define.

    `fecha_corte_carga_inicial` separa las dos épocas: hasta esa fecha inclusive,
    los cheques que se cargan son inventario preexistente y NO asientan el egreso
    de compra (esa plata salió antes, y el efectivo inicial ya la tiene
    descontada); a partir del día siguiente, la operación es normal.

    Es una tabla **singleton**: una sola fila, con `id = 1` forzado por un CHECK.
    """

    __tablename__ = "configuracion_apertura"
    __table_args__ = (
        sa.CheckConstraint("id = 1", name="ck_configuracion_apertura_singleton"),
        sa.CheckConstraint(
            "saldo_inicial_ars IS NULL OR saldo_inicial_ars >= 0",
            name="ck_configuracion_apertura_ars_no_negativo",
        ),
        sa.CheckConstraint(
            "saldo_inicial_usd IS NULL OR saldo_inicial_usd >= 0",
            name="ck_configuracion_apertura_usd_no_negativo",
        ),
    )

    id: Mapped[int] = mapped_column(sa.Integer(), primary_key=True, default=1)

    fecha_corte_carga_inicial: Mapped[date | None] = mapped_column(sa.Date(), nullable=True)
    saldo_inicial_ars:         Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    saldo_inicial_usd:         Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 2), nullable=True)
    # $/USD promedio al que se consiguió el stock inicial de dólares: es el costo
    # contra el que se calcula la ganancia de las primeras ventas (migración 0019).
    cotizacion_usd_inicial:    Mapped[Decimal | None] = mapped_column(sa.Numeric(18, 4), nullable=True)
    # Día al que corresponde ese efectivo, NO el día en que se tipeó: se puede
    # cargar una semana después y el reporte igual cierra bien para atrás.
    fecha_saldo_inicial:       Mapped[date | None] = mapped_column(sa.Date(), nullable=True)

    definido_por: Mapped[str | None]      = mapped_column(sa.String(80), nullable=True)
    definido_at:  Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), server_default=sa.func.now())
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()
    )

    @property
    def saldo_definido(self) -> bool:
        """True si ya se cargó el efectivo de apertura (es por única vez)."""
        return self.definido_at is not None
