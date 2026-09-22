from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.db.models import ChequeEstado, ChequeTipo, MedioPago
from app.schemas.fiados import FiadoRead


# ── Los cheques que el cliente entrega para pagar ─────────────────────
#
# Un pago casi nunca es un solo papel: el cliente junta los cheques que tiene a
# mano —"me entregó estos tres al 5%"— y con eso salda lo que debe. Los tres
# entran a cartera por separado (cada uno vence y se cobra por su cuenta) pero
# la deuda baja por la **suma de sus valores netos**, que es una sola operación.
# Vive acá porque lo usan los dos cobros consolidados (§2.c) y el de un préstamo
# (§3): si cada uno definiera el suyo, terminarían aceptando cosas distintas.


class ChequeEntregado(BaseModel):
    """Uno de los cheques de un pago, con el descuento al que se toma."""

    # Puede faltar: un e-cheq recién emitido todavía no trae número (§E-cheq).
    nro_cheque: str | None = Field(default=None, min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    # El descuento pactado. Suele ser el mismo para todos los del lote, pero se
    # declara por cheque: un papel a 30 días y otro a 90 no valen lo mismo.
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    fecha_emision: date | None = None
    fecha_pago: date | None = None

    @property
    def valor_neto(self) -> Decimal:
        """Lo que este cheque salda: nominal menos el descuento."""
        return (self.monto * (Decimal("100") - self.porcentaje_compra) / Decimal("100")).quantize(
            Decimal("0.01")
        )


class PagoConCheques(BaseModel):
    """Los cheques con los que se paga, en lista o en la forma vieja de uno solo.

    Los cobros que la heredan aceptan las dos maneras: `cheques` con todos los
    papeles, o los campos sueltos de un único cheque —que es como venían las
    llamadas viejas del panel y del bot—. El validador normaliza a `cheques`, de
    modo que el servicio tiene **un solo camino** para leer el pago.
    """

    cheques: list[ChequeEntregado] = Field(default_factory=list)
    # ── Forma vieja: un cheque en campos sueltos ──────────────────────
    nro_cheque_pago: str | None = Field(default=None, min_length=1, max_length=64)
    banco_pago: str | None = Field(default=None, max_length=120)
    monto_cheque: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    porcentaje_compra_cheque: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    fecha_emision: date | None = None
    fecha_pago: date | None = None

    @model_validator(mode="after")
    def normalizar_cheques(self) -> PagoConCheques:
        if self.cheques:
            return self
        if self.monto_cheque is None or self.porcentaje_compra_cheque is None:
            raise ValueError(
                "Falta el cheque: mandá `cheques` o el monto y el porcentaje de uno."
            )
        self.cheques = [
            ChequeEntregado(
                nro_cheque=self.nro_cheque_pago,
                banco=self.banco_pago,
                monto=self.monto_cheque,
                porcentaje_compra=self.porcentaje_compra_cheque,
                fecha_emision=self.fecha_emision,
                fecha_pago=self.fecha_pago,
            )
        ]
        return self

    @property
    def valor_neto_total(self) -> Decimal:
        """Lo que el pago salda: la suma de los netos de todos los papeles."""
        return sum((c.valor_neto for c in self.cheques), Decimal("0.00")).quantize(
            Decimal("0.01")
        )


class ChequeCreate(BaseModel):
    # Opcional: el comprobante de emisión de un e-cheq no trae número (§E-cheq).
    # Se carga sin él y se completa después; el bot avisa cuando falta.
    nro_cheque: str | None = Field(default=None, min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal = Field(gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)
    cliente_origen_id: UUID | None = None
    # Papel o e-cheq. Etiqueta: entra a la misma cartera y suma al mismo total.
    # Default PAPEL porque es el caso normal y porque así ninguna carga existente
    # —ni un cliente viejo de la API— cambia de significado al agregarse el campo.
    tipo: ChequeTipo = ChequeTipo.PAPEL
    # Pesos efectivamente abonados por el cheque. None = se pagó todo, la operación
    # normal. Si es menor al valor neto (`monto × (1 − %compra)`), la diferencia
    # queda a deber: no sale de la caja y genera el pasivo con quien lo vendió
    # (§Comprar sin abonar).
    monto_abonado: Decimal | None = Field(
        default=None, ge=0, max_digits=18, decimal_places=2
    )
    # Dólares entregados al vendedor como parte del pago, y a cuánto se los tomó
    # (§Cheque pagado en dólares). Van juntos o no va ninguno. Lo que cubren en
    # pesos es `usd_entregados × cotizacion_usd`; el resto del valor neto sale de
    # la caja ARS (`monto_abonado`) o queda a deber.
    usd_entregados: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=2
    )
    cotizacion_usd: Decimal | None = Field(
        default=None, gt=0, max_digits=18, decimal_places=6
    )
    # Por cuál de las dos cajas salió lo abonado (§Caja paralela). No es columna
    # del cheque: solo viaja hasta la línea de caja de la compra.
    medio_pago: MedioPago = MedioPago.EFECTIVO
    # Y por cuál salieron los dólares, que puede no ser la misma: "le transferí
    # los pesos y le di los billetes". Mismo criterio que la compra de divisas,
    # que lleva sus dos medios por separado.
    medio_usd: MedioPago = MedioPago.EFECTIVO

    @model_validator(mode="after")
    def validate_fechas(self) -> "ChequeCreate":
        if (
            self.fecha_emision is not None
            and self.fecha_pago is not None
            and self.fecha_pago < self.fecha_emision
        ):
            raise ValueError("fecha_pago no puede ser anterior a fecha_emision.")
        return self

    @model_validator(mode="after")
    def validate_monto_abonado(self) -> "ChequeCreate":
        # Los dólares y su cotización son una sola cosa: con unos sin la otra no
        # hay forma de saber cuántos pesos del cheque cubrieron.
        if (self.usd_entregados is None) != (self.cotizacion_usd is None):
            raise ValueError(
                "Para pagar un cheque en dólares hacen falta los dos datos: "
                "cuántos dólares le diste y a cuánto se los tomaste."
            )

        # Lo que se paga por un cheque es su valor neto, no el nominal: un cheque
        # de $1.000.000 al 10% se compra por $900.000, y eso es lo que se debe.
        neto = (
            self.monto * (Decimal("100") - self.porcentaje_compra) / Decimal("100")
        ).quantize(Decimal("0.01"))

        # Los dólares cubren parte del precio, valuados a la cotización pactada.
        # El resto se paga en pesos (`monto_abonado`) o queda a deber.
        cubierto_usd = (
            (self.usd_entregados * self.cotizacion_usd).quantize(Decimal("0.01"))
            if self.usd_entregados is not None and self.cotizacion_usd is not None
            else Decimal("0.00")
        )
        if cubierto_usd > neto:
            # Pagar de más falla, no se acomoda solo (decisión del dueño): con la
            # cotización de por medio el error típico es un dedazo en la
            # cotización o en los dólares, y acomodarlo dejaría el cheque
            # "comprado" por un valor que nadie pactó.
            raise ValueError(
                f"Le diste {self.usd_entregados} USD a ${self.cotizacion_usd} = "
                f"${cubierto_usd}, y el cheque se compra por ${neto} (neto al "
                f"{self.porcentaje_compra}%): los dólares se pasan por "
                f"${cubierto_usd - neto}."
            )
        # Lo que queda del precio después de los dólares. Sin dólares de por
        # medio es el valor neto entero, que es como funcionó siempre.
        restante = (neto - cubierto_usd).quantize(Decimal("0.01"))

        if self.monto_abonado is None:
            # Se pagó todo: en pesos el resto, y nada queda a deber.
            return self
        if self.monto_abonado > restante:
            detalle_usd = (
                f" (${neto} netos menos ${cubierto_usd} que cubrieron los dólares)"
                if cubierto_usd > 0
                else f" (neto al {self.porcentaje_compra}%)"
            )
            raise ValueError(
                f"Abonaste ${self.monto_abonado} en pesos y falta pagar "
                f"${restante}{detalle_usd}: no puede superar ese valor."
            )
        if self.monto_abonado < restante and self.cliente_origen_id is None:
            raise ValueError(
                "Un cheque comprado a deber necesita el vendedor: indicá a quién "
                "le quedás debiendo."
            )
        return self


class ChequeUpdate(BaseModel):
    """Corrección de la carga de un cheque desde el panel.

    Todos los campos son opcionales: se aplican solo los presentes en el body
    (`exclude_unset`). Los campos que mueven plata (`monto`, `porcentaje_compra`,
    `porcentaje_venta`) recalculan ganancia/fiado/caja en el servicio. El servicio
    rechaza editar cheques en estado terminal (COBRADO/RECHAZADO) y fijar
    `porcentaje_venta`/`cliente_destino_id` en cheques que aún no se vendieron/fiaron.
    """

    nro_cheque: str | None = Field(default=None, min_length=1, max_length=64)
    banco: str | None = Field(default=None, max_length=120)
    monto: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=2)
    fecha_emision: date | None = None
    fecha_pago: date | None = None
    porcentaje_compra: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    porcentaje_venta: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_origen_id: UUID | None = None
    cliente_destino_id: UUID | None = None
    # Editable en cualquier estado no terminal: el tipo es una etiqueta y no mueve
    # plata, así que corregir un e-cheq cargado como papel no recalcula nada.
    tipo: ChequeTipo | None = None


class ChequeManualTransition(BaseModel):
    target_state: ChequeEstado
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    porcentaje_venta: Decimal | None = Field(
        default=None, ge=0, le=100, max_digits=7, decimal_places=4
    )
    cliente_destino_id: UUID | None = None
    # Por cuál de las dos cajas entró lo cobrado al vender o cobrar el cheque.
    medio_pago: MedioPago = MedioPago.EFECTIVO


class ChequeFiarRequest(BaseModel):
    operador_id: str = Field(min_length=1, max_length=80)
    motivo: str = Field(min_length=1)
    cliente_destino_id: UUID
    porcentaje_venta: Decimal = Field(ge=0, le=100, max_digits=7, decimal_places=4)


class ChequeRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    # Puede faltar: un e-cheq cargado desde un comprobante de emisión no trae
    # número (§E-cheq). Si esto vuelve a ser `str`, FastAPI no falla solo en esa
    # fila: **rechaza la respuesta entera** y el listado de cartera devuelve 500
    # con un `ResponseValidationError`. Un solo cheque sin número deja la pantalla
    # en blanco, y el panel no muestra ningún error —solo un contador en cero—.
    nro_cheque: str | None
    banco: str | None
    monto: Decimal
    fecha_emision: date | None
    fecha_pago: date | None
    porcentaje_compra: Decimal
    # Cuánto se abonó al comprarlo. None = se pagó todo; menos que el valor neto
    # significa que hay un pasivo abierto con el vendedor (§Comprar sin abonar).
    monto_abonado: Decimal | None
    # Parte del precio pagada en dólares, y a cuánto se tomó cada uno. None = la
    # compra fue solo en pesos, que es el caso normal (§Cheque pagado en dólares).
    usd_entregados: Decimal | None
    cotizacion_usd: Decimal | None
    porcentaje_venta: Decimal | None
    ganancia: Decimal
    estado: ChequeEstado
    tipo: ChequeTipo
    ultimo_evento_manual_at: datetime | None
    ultimo_operador_id: str | None
    ultimo_motivo_manual: str | None
    cliente_origen_id: UUID | None
    cliente_destino_id: UUID | None
    # A qué acreedor se le entregó para pagarle una deuda del negocio (§5). La
    # entrega deja el cheque en VENDIDO igual que una venta: sin esto el panel no
    # puede decir "entregado a Pedro" y la mostraría como una venta sin cliente.
    acreedor_destino: str | None = None
    tiene_foto: bool
    # Qué vuelta de este mismo papel por el negocio es esta fila (§Recompra). 1 = la
    # primera y única, que es el caso normal; 2 o más significa que el cheque se
    # vendió, siguió girando en plaza y el negocio lo volvió a comprar. Lo calcula
    # `list_cheques` en una sola consulta —no está en la tabla— y por eso vale 1
    # cuando el cheque llega por un endpoint que no lo computa.
    vuelta: int = 1
    created_at: datetime
    updated_at: datetime


class ChequeFiarResponse(BaseModel):
    cheque: ChequeRead
    fiado: FiadoRead


class FiadoCobrarConChequeResponse(BaseModel):
    fiado: FiadoRead
    cheque_ingresado: ChequeRead
    diferencia: Decimal
