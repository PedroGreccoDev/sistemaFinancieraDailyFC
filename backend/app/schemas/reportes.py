from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class SaldoPasivos(BaseModel):
    """Snapshot de pasivos pendientes al momento del arqueo (no filtrado por periodo)."""
    pendiente_ars: Decimal
    pendiente_usd: Decimal


class GastoPorConcepto(BaseModel):
    """Cuánto se gastó en una cosa dentro del período consultado.

    A diferencia de los dos snapshots, esto **sí se filtra por período**: es plata
    que salió en estos días, no un saldo. Sale del libro de caja —las líneas
    `GASTO`— y no de la tabla `gastos_operativos`, para que el total no pueda
    diferir de los egresos que muestra la caja de arriba: es la misma fuente.
    """

    concepto: str
    moneda: str
    total: Decimal


class PlataEnLaCalle(BaseModel):
    """Lo que el negocio tiene AFUERA al momento del arqueo (no filtrado por período).

    El espejo de `SaldoPasivos`: aquello es lo que el negocio debe, esto es lo que
    le deben. Van **separados por origen** porque se cobran en pantallas distintas
    (§2.c): `creditos` son los préstamos, que se cobran en Créditos, y `deudores`
    los fiados y las deudas libres, que se cobran en Deudores.

    En los dos casos el número es **lo que falta cobrar**, no lo que se entregó: un
    préstamo cobrado a medias ya no está entero en la calle. Y las monedas nunca se
    suman entre sí.
    """

    creditos_ars: Decimal
    creditos_usd: Decimal
    deudores_ars: Decimal
    deudores_usd: Decimal


class CajaPorMedio(BaseModel):
    """Una de las dos cajas paralelas de una moneda (§Caja paralela).

    El efectivo se cuadra contra los billetes del cajón y la transferencia contra
    el resumen del banco, así que cada una lleva sus propios totales y su propio
    saldo. Sumarlas da los totales de la moneda, pero es la suma la que no se
    puede contar contra nada.
    """

    medio: str
    ingresos_total: Decimal
    egresos_total: Decimal
    neto: Decimal
    saldo_apertura: Decimal = Decimal("0.00")
    saldo_cierre: Decimal = Decimal("0.00")


class CajaMoneda(BaseModel):
    """Caja de una moneda: totales de ingresos/egresos, neto y saldos.

    `saldo_apertura` es la plata que había al abrir el período (todo lo anterior,
    incluido el efectivo de arranque del sistema) y `saldo_cierre` lo que queda al
    final. El `neto` sigue siendo el flujo del período: un día de solo compras da
    negativo —correcto, salió plata— sin que por eso el saldo esté en rojo.
    """
    moneda: str
    ingresos_total: Decimal
    egresos_total: Decimal
    neto: Decimal
    saldo_apertura: Decimal = Decimal("0.00")
    saldo_cierre: Decimal = Decimal("0.00")
    # Las dos cajas por separado. Los totales de arriba son su suma: sirven para
    # leer el flujo del negocio, pero **el cierre del día se hace contra estos**
    # —contando billetes de un lado y mirando el banco del otro—.
    efectivo: CajaPorMedio | None = None
    transferencia: CajaPorMedio | None = None


class ReporteCajaRead(BaseModel):
    """Caja diaria de flujo real: ingresos y egresos efectivos, separados por moneda."""
    desde: date
    hasta: date
    ars: CajaMoneda
    usd: CajaMoneda
    # Ganancia FIFO realizada por venta de divisas en el período (dato, no movimiento).
    ganancia_divisas: Decimal
    saldo_pasivos: SaldoPasivos
    # Lo que está afuera, el espejo del anterior. Snapshot al día de hoy, sin
    # filtro de período: no es plata que se movió, es plata que falta volver.
    plata_en_calle: PlataEnLaCalle
    # En qué se fue la plata en el período. Ordenado de mayor a menor, ARS primero.
    gastos_periodo: list[GastoPorConcepto]


class MovimientoUnificadoRead(BaseModel):
    """Una operación del historial unificado de Movimientos.

    Feed completo de TODO lo que pasa en el negocio, venga del bot o del panel:
    - Toda fila del libro de caja (`movimientos_caja`): cobros (parciales y
      totales), ventas/compras/cobros de cheque, compra/venta de USD,
      otorgamientos, gastos, pagos de pasivo y vueltos.
    - Los ingresos de cheques a cartera (evento sin movimiento de efectivo).
    - Las salidas de cartera que tampoco mueven efectivo: el cheque fiado a un
      cliente, el entregado a un acreedor para pagarle y el rechazado. (La
      venta y el cobro sí mueven plata y vienen del libro de caja.)
    - Las compensaciones: el cliente le transfirió derecho a un acreedor del
      negocio y bajaron las dos deudas sin que la caja se moviera
      (§Compensación). La descripción dice quién le transfirió a quién.

    `flujo` = INGRESO | EGRESO (según el tipo de caja) | NEUTRO (eventos sin
    plata: un cheque que entra a cartera, una compensación). `grupo` es la
    familia de operación para filtrar en el panel.
    """
    id: str
    fecha: date
    moneda: str  # ARS | USD
    grupo: str  # COBROS | CHEQUES | DIVISAS | GASTOS | OTORGAMIENTOS | PASIVOS | COMPENSACIONES
    categoria: str  # CajaCategoria original, o uno de los eventos sin efectivo:
    # INGRESO_CHEQUE | FIADO_CHEQUE | ENTREGA_CHEQUE | RECHAZO_CHEQUE | COMPENSACION
    flujo: str  # INGRESO | EGRESO | NEUTRO
    descripcion: str
    monto: Decimal
    ganancia: Decimal | None  # solo VENTA_USD
    # Null solo en los eventos sin efectivo (un cheque que entra o sale de
    # cartera sin plata, una compensación): no pasaron por ninguna de las dos cajas.
    medio_pago: str | None
    cotizacion: Decimal | None  # $/USD si el pago cruzó monedas
    referencia_tipo: str | None
    referencia_id: UUID | None


class CuotaCobradaHistorialItem(BaseModel):
    cuota_id: UUID
    prestamo_id: UUID
    cliente_id: UUID
    cliente_nombre: str
    numero_cuota: int
    monto: Decimal
    moneda: str
    fecha_cobro: date
    fecha_vencimiento: date
