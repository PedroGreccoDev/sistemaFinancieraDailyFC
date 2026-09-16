from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.db.models import (
    CajaCategoria,
    CajaTipo,
    Cheque,
    ChequeEstado,
    ChequeTipo,
    Cliente,
    Compensacion,
    Cuota,
    DeudaSimple,
    Fiado,
    FiadoEstado,
    Evento,
    Prestamo,
    Pasivo,
    PasivoEstado,
    MedioPago,
    Moneda,
    MovimientoCaja,
)
from app.services import reportes as service
from app.services.exceptions import ValidationError


class FakeDB:
    """Stand-in mínimo de Session: `scalars` devuelve los result-sets encolados.

    El servicio consulta, en orden: `movimientos_caja`, `cheques` (los que
    entraron a cartera), las `compensaciones`, los `fiados`, los cheques que
    salieron de cartera sin plata, las líneas de venta que distinguen una venta
    de una entrega, los `pasivos` y los `eventos`. Este stub ignora el statement y va entregando las listas
    en ese orden. Una consulta para la que no se encoló nada devuelve vacío: el
    día que el feed sume otra fuente, los tests que no la miran no tienen por
    qué romperse.
    """

    def __init__(self, *result_sets: list, origenes: dict | None = None) -> None:
        self._queue = list(result_sets)
        # Las entidades de origen de los cobros, por modelo: {Fiado: [fiado, ...]}.
        # Se guardan **objetos del modelo**, no tuplas ya armadas, y `execute`
        # lee de cada uno las columnas que el statement pide: así el test falla
        # si el servicio busca la fecha en la tabla —o en la columna— equivocada.
        self._origenes = origenes or {}
        self.consultas_origen = 0

    def scalars(self, _stmt):  # noqa: ANN001
        return iter(self._queue.pop(0) if self._queue else [])

    def execute(self, stmt):  # noqa: ANN001
        self.consultas_origen += 1
        columnas = stmt.column_descriptions
        principal = columnas[0]["entity"]

        def _relacionado(obj, clase, profundidad=2):  # noqa: ANN001
            """El objeto de `clase` colgado de `obj`, hasta dos saltos.

            Los dos saltos son para la cuota: el cliente no cuelga de ella sino
            del préstamo (`cuota.prestamo.cliente`), igual que en el join real.
            """
            if profundidad == 0:
                return None
            valores = list(vars(obj).values())
            directo = next((v for v in valores if isinstance(v, clase)), None)
            if directo is not None:
                return directo
            for v in valores:
                if hasattr(v, "__dict__"):
                    hallado = _relacionado(v, clase, profundidad - 1)
                    if hallado is not None:
                        return hallado
            return None

        def _valor(obj, col):  # noqa: ANN001
            # Una columna de otra entidad (el `fecha_inicio` del préstamo al que
            # cuelga la cuota, el nombre del cliente) se lee del relacionado.
            if col["entity"] is not principal:
                obj = _relacionado(obj, col["entity"])
                if obj is None:
                    return None
            return getattr(obj, col["name"], None)

        return iter(
            tuple(_valor(obj, col) for col in columnas)
            for obj in self._origenes.get(principal, [])
        )


def _caja(
    *,
    fecha: date,
    categoria: CajaCategoria,
    tipo: CajaTipo,
    monto: str,
    moneda: Moneda = Moneda.ARS,
    detalle: str | None = None,
    ganancia: str | None = None,
    # Toda línea del libro cae en una de las dos cajas: el medio es NOT NULL desde
    # la migración `0026` (§Caja paralela). El default refleja ese invariante.
    medio_pago: MedioPago = MedioPago.EFECTIVO,
    cotizacion: str | None = None,
    referencia_tipo: str | None = None,
    referencia_id: uuid.UUID | None = None,
) -> MovimientoCaja:
    return MovimientoCaja(
        id=uuid.uuid4(),
        fecha=fecha,
        moneda=moneda,
        tipo=tipo,
        categoria=categoria,
        monto=Decimal(monto),
        ganancia=None if ganancia is None else Decimal(ganancia),
        medio_pago=medio_pago,
        cotizacion=None if cotizacion is None else Decimal(cotizacion),
        referencia_tipo=referencia_tipo,
        referencia_id=(
            referencia_id
            if referencia_id is not None
            else (uuid.uuid4() if referencia_tipo else None)
        ),
        detalle=detalle,
    )


def _cheque(*, created_at: datetime, estado: ChequeEstado = ChequeEstado.EN_CARTERA,
            cliente: Cliente | None = None, nro: str | None = "123", banco: str | None = None,
            monto: str = "100000") -> Cheque:
    c = Cheque(
        id=uuid.uuid4(),
        nro_cheque=nro,
        banco=banco,
        monto=Decimal(monto),
        porcentaje_compra=Decimal("0"),
        estado=estado,
    )
    c.created_at = created_at
    c.cliente_origen = cliente
    return c


DESDE = date(2026, 7, 1)
HASTA = date(2026, 7, 31)


def test_rango_invalido_lanza():
    with pytest.raises(ValidationError):
        service.get_movimientos_unificados(FakeDB([], []), HASTA, DESDE)


def test_incluye_lineas_de_caja_con_grupo_y_flujo():
    caja = [
        _caja(fecha=date(2026, 7, 10), categoria=CajaCategoria.COBRO_CUOTA,
              tipo=CajaTipo.INGRESO, monto="500.00", detalle="Cuota #1 - Ana"),
        _caja(fecha=date(2026, 7, 12), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="200.00", detalle="Nafta"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    assert len(items) == 2
    por_cat = {i.categoria: i for i in items}
    assert por_cat["COBRO_CUOTA"].grupo == "COBROS"
    assert por_cat["COBRO_CUOTA"].flujo == "INGRESO"
    assert por_cat["COBRO_CUOTA"].descripcion == "Cuota #1 - Ana"
    assert por_cat["GASTO"].grupo == "GASTOS"
    assert por_cat["GASTO"].flujo == "EGRESO"


def test_ingreso_de_cheque_es_neutro_y_en_grupo_cheques():
    cliente = Cliente(id=uuid.uuid4(), nombre="Pedro")
    cheques = [_cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                       cliente=cliente, nro="777", banco="Nación")]
    items = service.get_movimientos_unificados(FakeDB([], cheques), DESDE, HASTA)
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "INGRESO_CHEQUE"
    assert it.grupo == "CHEQUES"
    assert it.flujo == "NEUTRO"
    assert it.moneda == "ARS"
    assert it.referencia_tipo == "cheque"
    assert "777" in it.descripcion and "Pedro" in it.descripcion and "Nación" in it.descripcion


def test_cheque_fuera_de_rango_local_se_excluye():
    # 2026-08-01 02:00 UTC = 2026-07-31 23:00 ART -> entra (día 31).
    dentro = _cheque(created_at=datetime(2026, 8, 1, 2, 0, tzinfo=timezone.utc), nro="IN")
    # 2026-08-01 04:00 UTC = 2026-08-01 01:00 ART -> queda fuera del rango.
    fuera = _cheque(created_at=datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc), nro="OUT")
    items = service.get_movimientos_unificados(FakeDB([], [dentro, fuera]), DESDE, HASTA)
    nros = [i.descripcion for i in items]
    assert any("IN" in d for d in nros)
    assert not any("OUT" in d for d in nros)


def test_orden_por_fecha_descendente():
    caja = [
        _caja(fecha=date(2026, 7, 5), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="10.00"),
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="20.00"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    assert [i.fecha for i in items] == [date(2026, 7, 20), date(2026, 7, 5)]


def test_venta_usd_expone_ganancia_y_cotizacion():
    caja = [
        _caja(fecha=date(2026, 7, 8), categoria=CajaCategoria.VENTA_USD,
              tipo=CajaTipo.INGRESO, monto="150000.00", ganancia="5000.00",
              detalle="Venta de 100 USD @ $1500", referencia_tipo="movimiento"),
    ]
    items = service.get_movimientos_unificados(FakeDB(caja, []), DESDE, HASTA)
    it = items[0]
    assert it.grupo == "DIVISAS"
    assert it.ganancia == Decimal("5000.00")
    assert it.referencia_tipo == "movimiento"


def test_un_echeq_sin_numero_no_se_muestra_como_None():
    """Se vio en pantalla: "Ingreso cheque Nº None de Paolini Hnos".

    El número puede faltar (§E-cheq) y esta línea lo interpolaba a mano, así que
    el `None` de Python llegaba tal cual a la pantalla de movimientos. El nombre
    lo arma `describir`, que es el único lugar que sabe qué hacer sin número.
    """
    cliente = Cliente(id=uuid.uuid4(), nombre="Paolini Hnos")
    sin_numero = _cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                         cliente=cliente, nro=None, banco=None, monto="1234567.00")
    sin_numero.tipo = ChequeTipo.ELECTRONICO
    items = service.get_movimientos_unificados(FakeDB([], [sin_numero]), DESDE, HASTA)
    assert "None" not in items[0].descripcion
    assert "e-cheq sin número ($1,234,567.00)" in items[0].descripcion
    assert "Paolini Hnos" in items[0].descripcion


def test_un_echeq_con_numero_se_nombra_como_echeq():
    """La misma pantalla llamaba "cheque" a un e-cheq: el operador no podía
    distinguir en la lista qué papel entró y cuál no existe."""
    con_numero = _cheque(created_at=datetime(2026, 7, 15, 15, 0, tzinfo=timezone.utc),
                         nro="00001020", banco="Galicia")
    con_numero.tipo = ChequeTipo.ELECTRONICO
    items = service.get_movimientos_unificados(FakeDB([], [con_numero]), DESDE, HASTA)
    assert "e-cheq Nº 00001020 — Galicia" in items[0].descripcion


# ══════════════════════════════════════════════════════════════════════
#  Compensaciones: el evento sin efectivo que no se veía en ningún lado
# ══════════════════════════════════════════════════════════════════════

def _compensacion(
    *,
    fecha: date = date(2026, 7, 18),
    cliente: str = "Juan",
    acreedor: str = "Pedro",
    monto: str = "600000",
    moneda: Moneda = Moneda.ARS,
    moneda_deuda: Moneda = Moneda.ARS,
    moneda_pasivo: Moneda = Moneda.ARS,
    imputado_cliente: str | None = None,
    imputado_pasivo: str | None = None,
    excedente: str = "0",
    cotizacion: str | None = None,
) -> Compensacion:
    comp = Compensacion(
        id=uuid.uuid4(),
        fecha=fecha,
        cliente_id=uuid.uuid4(),
        acreedor=acreedor,
        moneda_pasivo=moneda_pasivo,
        moneda=moneda,
        monto=Decimal(monto),
        moneda_deuda=moneda_deuda,
        cotizacion=None if cotizacion is None else Decimal(cotizacion),
        imputado_cliente=Decimal(imputado_cliente if imputado_cliente is not None else monto),
        imputado_pasivo=Decimal(imputado_pasivo if imputado_pasivo is not None else monto),
        excedente=Decimal(excedente),
    )
    comp.cliente = Cliente(id=comp.cliente_id, nombre=cliente)
    return comp


def test_la_compensacion_aparece_como_evento_sin_efectivo():
    """Sin línea de caja, la operación no figuraba en ninguna pantalla del día.

    Bajan dos deudas y la caja no se mueve (§Compensación), así que el libro no
    la tiene; el operador igual necesita verla, y con los dos nombres: el
    registro de quién le transfirió a quién es todo lo que queda de ella.
    """
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "COMPENSACION"
    assert it.grupo == "COMPENSACIONES"
    assert it.flujo == "NEUTRO"
    assert it.monto == Decimal("600000.00")
    assert it.referencia_tipo == "compensacion"
    # Las dos puntas, en la dirección correcta: Juan le transfirió a Pedro.
    assert it.descripcion == "Compensación: Juan le transfirió a Pedro"


def test_la_compensacion_no_declara_medio_de_pago():
    # Ninguna de las dos cajas se movió: la plata fue de un tercero a otro.
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert items[0].medio_pago is None


def test_cross_moneda_muestra_cuanto_bajo_cada_lado():
    # Juan transfirió $600.000 contra una deuda suya en dólares: el monto de la
    # columna y lo que bajó la deuda son números distintos, y sin decirlo la
    # línea no se entiende.
    comp = _compensacion(
        moneda=Moneda.ARS,
        monto="600000",
        moneda_deuda=Moneda.USD,
        imputado_cliente="500",
        cotizacion="1200",
    )
    items = service.get_movimientos_unificados(FakeDB([], [], [comp]), DESDE, HASTA)
    it = items[0]
    assert "baja la deuda de Juan: U$D 500.00" in it.descripcion
    assert it.cotizacion == Decimal("1200")


def test_el_excedente_a_favor_se_nombra():
    # Transfirió más de lo que debía: la diferencia le quedó a favor y eso es
    # parte de lo que pasó ese día.
    comp = _compensacion(monto="700000", imputado_cliente="600000", excedente="100000")
    items = service.get_movimientos_unificados(FakeDB([], [], [comp]), DESDE, HASTA)
    descripcion = items[0].descripcion
    assert "baja la deuda de Juan: $600,000.00" in descripcion
    assert "a favor de Juan: $100,000.00" in descripcion


def test_compensacion_comun_no_repite_el_mismo_numero_tres_veces():
    # Misma moneda y sin excedente: el monto transferido, lo que bajó el cliente
    # y lo que bajó el acreedor son el mismo número, y la columna ya lo muestra.
    items = service.get_movimientos_unificados(
        FakeDB([], [], [_compensacion()]), DESDE, HASTA
    )
    assert "baja la deuda" not in items[0].descripcion


def test_las_compensaciones_se_ordenan_con_el_resto_del_dia():
    caja = [
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="10.00"),
    ]
    comp = [_compensacion(fecha=date(2026, 7, 25))]
    items = service.get_movimientos_unificados(FakeDB(caja, [], comp), DESDE, HASTA)
    assert [i.fecha for i in items] == [date(2026, 7, 25), date(2026, 7, 20)]


# ══════════════════════════════════════════════════════════════════════
#  Las tres salidas de cartera que no mueven plata
# ══════════════════════════════════════════════════════════════════════
#
# Un cheque sale de cartera de cinco maneras y solo la venta y el cobro dejan
# plata: esas dos ya vienen del libro de caja. Las otras tres —fiarlo,
# entregárselo a un acreedor y el rechazo— entraban a cartera a la vista de
# todos y se iban en silencio.

def _fiado(
    *,
    fecha: date = date(2026, 7, 14),
    cliente: str = "Ana",
    nro: str = "555",
    monto: str = "100000",
    saldo: str = "90000",
) -> Fiado:
    f = Fiado(
        id=uuid.uuid4(),
        cheque_id=uuid.uuid4(),
        cliente_id=uuid.uuid4(),
        monto_original=Decimal(monto),
        porcentaje_venta=Decimal("10"),
        saldo_pendiente=Decimal(saldo),
        estado=FiadoEstado.ABIERTO,
        fecha_fiado=fecha,
    )
    f.cheque = _cheque(created_at=datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc),
                       estado=ChequeEstado.FIADO, nro=nro, monto=monto)
    f.cliente = Cliente(id=f.cliente_id, nombre=cliente)
    return f


def _salido(
    *,
    estado: ChequeEstado,
    evento: datetime = datetime(2026, 7, 16, 15, 0, tzinfo=timezone.utc),
    nro: str = "888",
    monto: str = "200000",
    acreedor_destino: str | None = None,
    porcentaje_venta: str | None = None,
    origen: Cliente | None = None,
) -> Cheque:
    c = _cheque(created_at=datetime(2026, 7, 2, 12, 0, tzinfo=timezone.utc),
                estado=estado, nro=nro, monto=monto, cliente=origen)
    c.ultimo_evento_manual_at = evento
    c.acreedor_destino = acreedor_destino
    c.porcentaje_venta = None if porcentaje_venta is None else Decimal(porcentaje_venta)
    return c


def test_el_cheque_fiado_se_ve_con_el_cliente_y_lo_que_queda_debiendo():
    items = service.get_movimientos_unificados(
        FakeDB([], [], [], [_fiado()]), DESDE, HASTA
    )
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "FIADO_CHEQUE"
    assert it.grupo == "CHEQUES"
    assert it.flujo == "NEUTRO"
    # El monto es el nominal del papel, como en el ingreso a cartera; lo que el
    # cliente debe es otro número y va en el texto.
    assert it.monto == Decimal("100000.00")
    assert it.descripcion == "Fiado cheque Nº 555 a Ana · queda debiendo $90,000.00"
    assert it.referencia_tipo == "fiado"


def test_el_cheque_entregado_a_un_acreedor_dice_a_quien_y_cuanta_deuda_cubre():
    entregado = _salido(estado=ChequeEstado.VENDIDO, acreedor_destino="Pedro",
                        porcentaje_venta="10", monto="200000")
    items = service.get_movimientos_unificados(
        FakeDB([], [], [], [], [entregado], []), DESDE, HASTA
    )
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "ENTREGA_CHEQUE"
    assert it.flujo == "NEUTRO"
    assert it.medio_pago is None
    assert it.descripcion == (
        "Entregado cheque Nº 888 a Pedro a cuenta de una deuda · "
        "cubre $180,000.00 de deuda"
    )


def test_una_venta_de_verdad_no_se_duplica_como_entrega():
    """Las dos salidas dejan el cheque en VENDIDO: lo que las separa es la plata.

    La venta ya viene por el libro de caja; si además saliera por acá, el mismo
    cheque aparecería dos veces el mismo día.
    """
    vendido = _salido(estado=ChequeEstado.VENDIDO, porcentaje_venta="10")
    caja = [
        _caja(fecha=date(2026, 7, 16), categoria=CajaCategoria.VENTA_CHEQUE,
              tipo=CajaTipo.INGRESO, monto="180000.00", detalle="Venta cheque Nº 888"),
    ]
    # La última cola son los ids con ingreso de venta: el del cheque vendido.
    items = service.get_movimientos_unificados(
        FakeDB(caja, [], [], [], [vendido], [vendido.id]), DESDE, HASTA
    )
    assert len(items) == 1
    assert items[0].categoria == "VENTA_CHEQUE"


def test_la_entrega_vieja_sin_nombre_se_muestra_igual():
    # Antes de la columna `acreedor_destino` (0032) no se guardaba a quién se le
    # entregó. Reconocerlas por la falta de ingreso en el libro —y no por la
    # columna— es lo que hace que esas sigan apareciendo.
    vieja = _salido(estado=ChequeEstado.VENDIDO, acreedor_destino=None,
                    porcentaje_venta="10")
    items = service.get_movimientos_unificados(
        FakeDB([], [], [], [], [vieja], []), DESDE, HASTA
    )
    assert items[0].categoria == "ENTREGA_CHEQUE"
    assert "a cuenta de una deuda" in items[0].descripcion
    assert "None" not in items[0].descripcion


def test_el_rechazo_se_ve_con_quien_trajo_el_cheque():
    origen = Cliente(id=uuid.uuid4(), nombre="Juan")
    rebotado = _salido(estado=ChequeEstado.RECHAZADO, nro="999", origen=origen)
    items = service.get_movimientos_unificados(
        FakeDB([], [], [], [], [rebotado], []), DESDE, HASTA
    )
    it = items[0]
    assert it.categoria == "RECHAZO_CHEQUE"
    assert it.flujo == "NEUTRO"
    assert it.descripcion == "Rechazado cheque Nº 999 (venía de Juan)"


def test_una_salida_fuera_del_rango_local_se_excluye():
    # 2026-08-01 04:00 UTC = 2026-08-01 01:00 ART: cayó en agosto.
    fuera = _salido(estado=ChequeEstado.RECHAZADO, nro="OUT",
                    evento=datetime(2026, 8, 1, 4, 0, tzinfo=timezone.utc))
    items = service.get_movimientos_unificados(
        FakeDB([], [], [], [], [fuera], []), DESDE, HASTA
    )
    assert items == []


# ══════════════════════════════════════════════════════════════════════
#  Deudas contraídas y plata a favor: lo que se debe sin que salga plata
# ══════════════════════════════════════════════════════════════════════

def _pasivo(
    *,
    acreedor: str = "Ferretería Pedro",
    concepto: str = "mercadería",
    monto: str = "200000",
    creado: datetime = datetime(2026, 7, 9, 15, 0, tzinfo=timezone.utc),
    origen_tipo: str | None = None,
    ingreso_caja: bool = False,
    moneda: Moneda = Moneda.ARS,
) -> Pasivo:
    p = Pasivo(
        id=uuid.uuid4(),
        acreedor=acreedor,
        concepto=concepto,
        monto=Decimal(monto),
        saldo_pendiente=Decimal(monto),
        moneda=moneda,
        estado=PasivoEstado.PENDIENTE,
        ingreso_caja=ingreso_caja,
        origen_tipo=origen_tipo,
    )
    p.created_at = creado
    return p


def _feed_pasivos(*pasivos: Pasivo):
    return service.get_movimientos_unificados(
        FakeDB([], [], [], [], [], [], list(pasivos)), DESDE, HASTA
    )


def test_la_deuda_con_un_proveedor_figura_el_dia_que_se_contrae():
    items = _feed_pasivos(_pasivo())
    assert len(items) == 1
    it = items[0]
    assert it.categoria == "DEUDA_CONTRAIDA"
    assert it.grupo == "PASIVOS"
    assert it.flujo == "NEUTRO"
    assert it.monto == Decimal("200000.00")
    assert it.descripcion == "Deuda con Ferretería Pedro · mercadería"


def test_lo_que_quedo_debiendo_de_una_compra_tambien_figura():
    """La compra a deber asienta el egreso de lo que se pagó y nada más.

    Lo que quedó debiendo no salía de la caja —correcto— pero tampoco aparecía
    en ningún lado: el día mostraba una compra y no la deuda que dejó.
    """
    items = _feed_pasivos(_pasivo(origen_tipo="cheque", concepto="Compra cheque Nº 12"))
    assert items[0].descripcion == (
        "Quedaste debiendo a Ferretería Pedro · Compra cheque Nº 12"
    )


def test_el_vuelto_que_queda_debiendo_se_nombra_al_reves():
    # No es lo mismo deberle al proveedor que tener plata de un cliente.
    items = _feed_pasivos(
        _pasivo(acreedor="Juan", concepto="Vuelto cheque Nº 77", monto="5000",
                origen_tipo="vuelto_cheque")
    )
    it = items[0]
    assert it.categoria == "SALDO_A_FAVOR"
    assert it.descripcion == "Queda a favor de Juan · Vuelto cheque Nº 77"


def test_el_prestamo_recibido_no_se_muestra_dos_veces():
    # Con `ingreso_caja` entró plata: ya viene del libro como INGRESO_PASIVO.
    assert _feed_pasivos(_pasivo(ingreso_caja=True)) == []


# ══════════════════════════════════════════════════════════════════════
#  El registro de operaciones: lo que no deja rastro en ninguna tabla
# ══════════════════════════════════════════════════════════════════════

def _evento(
    *,
    categoria: str = "ANULACION",
    grupo: str = "ANULACIONES",
    descripcion: str = "Anulado: Gasto nafta · motivo: se cargó dos veces",
    fecha: date = date(2026, 7, 21),
    monto: str | None = "10000",
    moneda: Moneda | None = Moneda.ARS,
) -> Evento:
    e = Evento(
        id=uuid.uuid4(),
        fecha=fecha,
        categoria=categoria,
        grupo=grupo,
        descripcion=descripcion,
        monto=None if monto is None else Decimal(monto),
        moneda=moneda,
        referencia_tipo="gasto",
        referencia_id=uuid.uuid4(),
        operador="op",
    )
    e.created_at = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)
    return e


def _feed_eventos(*eventos: Evento):
    return service.get_movimientos_unificados(
        FakeDB([], [], [], [], [], [], [], list(eventos)), DESDE, HASTA
    )


def test_la_anulacion_deja_constancia_en_el_dia():
    """Deshacer borra las líneas de caja: el renglón original desaparece.

    Sin el registro, un día que tenía un gasto y se anuló queda idéntico a un
    día en el que ese gasto nunca se cargó.
    """
    items = _feed_eventos(_evento())
    assert len(items) == 1
    it = items[0]
    assert it.grupo == "ANULACIONES"
    assert it.categoria == "ANULACION"
    assert it.flujo == "NEUTRO"  # el reverso de la plata ya lo hizo la anulación
    assert "se cargó dos veces" in it.descripcion


def test_la_correccion_cuenta_que_habia_antes():
    items = _feed_eventos(
        _evento(categoria="CORRECCION", grupo="CORRECCIONES", monto=None, moneda=None,
                descripcion="Corregido: gasto nafta · monto: 10.000,00 → 12.000,00")
    )
    it = items[0]
    assert it.categoria == "CORRECCION"
    # Sin monto propio: lo que cambió se lee en el texto.
    assert it.monto == Decimal("0.00")
    assert it.moneda == "ARS"


def test_el_cobro_con_cheque_figura_como_cobro():
    items = _feed_eventos(
        _evento(categoria="COBRO_CHEQUE_DEUDA", grupo="COBROS", monto="90000",
                descripcion="Juan pagó su cuenta con cheque Nº 123 — Nación")
    )
    it = items[0]
    assert it.grupo == "COBROS"
    assert it.monto == Decimal("90000.00")
    assert it.flujo == "NEUTRO"


# ── La hora de cada operación ─────────────────────────────────────────────


def test_cada_linea_de_caja_trae_su_momento():
    """El feed expone cuándo se registró la operación, no solo a qué día pertenece."""
    momento = datetime(2026, 7, 10, 21, 17, tzinfo=timezone.utc)
    linea = _caja(fecha=date(2026, 7, 10), categoria=CajaCategoria.GASTO,
                  tipo=CajaTipo.EGRESO, monto="200.00", detalle="Nafta")
    linea.created_at = momento

    items = service.get_movimientos_unificados(FakeDB([linea], []), DESDE, HASTA)
    assert items[0].momento == momento


def test_dentro_del_dia_ordena_por_hora_y_no_por_id():
    """A igual día, primero lo último que pasó.

    El desempate era el `id` —un UUID v4—, así que las operaciones de una misma
    jornada salían en orden aleatorio: un vuelto podía figurar arriba del cobro
    que lo generó. Se arma el caso con el UUID mayor en la línea más vieja, que
    es el que el orden anterior habría puesto primero.
    """
    dia = date(2026, 7, 10)
    temprano = _caja(fecha=dia, categoria=CajaCategoria.COBRO_CUOTA,
                     tipo=CajaTipo.INGRESO, monto="500.00", detalle="Cobro")
    tarde = _caja(fecha=dia, categoria=CajaCategoria.VUELTO_PASIVO,
                  tipo=CajaTipo.EGRESO, monto="100.00", detalle="Vuelto")
    temprano.created_at = datetime(2026, 7, 10, 9, 0, tzinfo=timezone.utc)
    tarde.created_at = datetime(2026, 7, 10, 18, 30, tzinfo=timezone.utc)
    # El id no puede ser el que decide: se le da al viejo el que ordenaría primero.
    temprano.id = uuid.UUID("ffffffff-ffff-4fff-8fff-ffffffffffff")
    tarde.id = uuid.UUID("00000000-0000-4000-8000-000000000000")

    items = service.get_movimientos_unificados(FakeDB([temprano, tarde], []), DESDE, HASTA)
    assert [i.descripcion for i in items] == ["Vuelto", "Cobro"]


def test_una_fila_sin_timestamp_no_rompe_el_orden():
    """`created_at` lo pone la base: una fila que todavía no lo tiene no puede tumbar el feed."""
    dia = date(2026, 7, 10)
    con_hora = _caja(fecha=dia, categoria=CajaCategoria.GASTO,
                     tipo=CajaTipo.EGRESO, monto="200.00", detalle="Con hora")
    con_hora.created_at = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)
    sin_hora = _caja(fecha=dia, categoria=CajaCategoria.GASTO,
                     tipo=CajaTipo.EGRESO, monto="300.00", detalle="Sin hora")

    items = service.get_movimientos_unificados(FakeDB([con_hora, sin_hora], []), DESDE, HASTA)
    assert len(items) == 2
    assert items[0].descripcion == "Con hora"   # la que tiene hora va primero
    assert items[1].momento is None


# ── Fecha de origen de los cobros ─────────────────────────────────────
#
# Un cobro por cliente imputa de la deuda más vieja a la más nueva y cada
# renglón asienta su propia línea, todas en la misma transacción: comparten
# `created_at` al microsegundo y su `id` es un UUID v4. `origen_fecha` es lo
# único con lo que el panel puede volver a armar ese orden.


def test_origen_fecha_sale_de_la_tabla_de_cada_referencia():
    """Cada tipo de cobro busca su fecha donde corresponde, no en cualquier tabla."""
    fiado_id, deuda_id, prestamo_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    caja = [
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_FIADO,
              tipo=CajaTipo.INGRESO, monto="100.00", detalle="Cobro fiado - Ana",
              referencia_tipo="fiado", referencia_id=fiado_id),
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_DEUDA,
              tipo=CajaTipo.INGRESO, monto="200.00", detalle="Cobro deuda - Ana - Envases",
              referencia_tipo="deuda_simple_cobro", referencia_id=deuda_id),
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_CUOTA,
              tipo=CajaTipo.INGRESO, monto="300.00", detalle="Pago préstamo - Ana",
              referencia_tipo="prestamo", referencia_id=prestamo_id),
    ]
    ana = Cliente(id=uuid.uuid4(), nombre="Ana Torres")
    fiado = Fiado(id=fiado_id, fecha_fiado=date(2026, 3, 1))
    fiado.cliente = ana
    # Con `fecha_cancelacion` cargada a propósito: es la otra fecha de la tabla,
    # y sacar la de ahí daría el día en que se terminó de pagar.
    deuda = DeudaSimple(id=deuda_id, fecha=date(2026, 4, 2),
                        fecha_cancelacion=date(2026, 7, 20))
    deuda.cliente = ana
    prestamo = Prestamo(id=prestamo_id, fecha_inicio=date(2026, 5, 3))
    prestamo.cliente = ana
    db = FakeDB(caja, [], origenes={
        Fiado: [fiado], DeudaSimple: [deuda], Prestamo: [prestamo],
    })
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    por_cat = {i.categoria: i.origen_fecha for i in items}
    assert por_cat["COBRO_FIADO"]  == date(2026, 3, 1)
    assert por_cat["COBRO_DEUDA"]  == date(2026, 4, 2)
    assert por_cat["COBRO_CUOTA"]  == date(2026, 5, 3)


def test_una_cuota_hereda_la_antiguedad_de_su_prestamo():
    """Lo que envejece es el crédito, no el renglón del cuadro de cuotas."""
    cuota_id = uuid.uuid4()
    caja = [_caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_CUOTA,
                  tipo=CajaTipo.INGRESO, monto="500.00", detalle="Cuota #3 - Ana",
                  referencia_tipo="cuota", referencia_id=cuota_id)]
    cuota = Cuota(id=cuota_id, fecha_vencimiento=date(2026, 6, 1))
    cuota.prestamo = Prestamo(id=uuid.uuid4(), fecha_inicio=date(2026, 1, 15))
    cuota.prestamo.cliente = Cliente(id=uuid.uuid4(), nombre="Ana Torres")
    db = FakeDB(caja, [], origenes={Cuota: [cuota]})
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    assert items[0].origen_fecha == date(2026, 1, 15)
    # El cliente también sale del préstamo, no de la cuota.
    assert items[0].origen_cliente == "Ana Torres"


def test_lo_que_no_es_cobro_no_trae_origen_fecha():
    """Solo los cobros se parten en varios renglones: el resto no paga la consulta."""
    caja = [
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.GASTO,
              tipo=CajaTipo.EGRESO, monto="200.00", detalle="Nafta"),
        _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.VENTA_CHEQUE,
              tipo=CajaTipo.INGRESO, monto="900.00", detalle="Venta cheque",
              referencia_tipo="cheque"),
    ]
    db = FakeDB(caja, [])
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    assert all(i.origen_fecha is None for i in items)
    assert all(i.origen_cliente is None for i in items)
    # Sin cobros no se consulta ninguna tabla de origen.
    assert db.consultas_origen == 0


def test_una_referencia_que_ya_no_existe_no_rompe_el_feed():
    """Un cobro cuya operación de origen se anuló sigue listándose, sin fecha."""
    caja = [_caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_FIADO,
                  tipo=CajaTipo.INGRESO, monto="100.00", detalle="Cobro fiado - Ana",
                  referencia_tipo="fiado", referencia_id=uuid.uuid4())]
    db = FakeDB(caja, [], origenes={Fiado: []})
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    assert len(items) == 1
    assert items[0].origen_fecha is None
    assert items[0].origen_cliente is None


def test_los_renglones_de_un_cobro_quedan_ordenables_por_antiguedad():
    """El caso real: un cobro que tapó tres deudas, todas con el mismo timestamp."""
    momento = datetime(2026, 7, 20, 15, 30, 45, 123456, tzinfo=timezone.utc)
    ids = [uuid.uuid4() for _ in range(3)]
    fechas = [date(2026, 5, 10), date(2026, 2, 1), date(2026, 4, 3)]
    caja = []
    for oid, monto in zip(ids, ("100.00", "200.00", "300.00")):
        linea = _caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_DEUDA,
                      tipo=CajaTipo.INGRESO, monto=monto, detalle=f"Cobro deuda - Ana - {monto}",
                      referencia_tipo="deuda_simple_cobro", referencia_id=oid)
        linea.created_at = momento
        caja.append(linea)

    ana = Cliente(id=uuid.uuid4(), nombre="Ana Torres")
    deudas = []
    for oid, f in zip(ids, fechas):
        d = DeudaSimple(id=oid, fecha=f)
        d.cliente = ana
        deudas.append(d)
    db = FakeDB(caja, [], origenes={DeudaSimple: deudas})
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    # Comparten momento: el orden del feed no los distingue, `origen_fecha` sí.
    assert len({i.momento for i in items}) == 1
    assert sorted(i.origen_fecha for i in items) == [
        date(2026, 2, 1), date(2026, 4, 3), date(2026, 5, 10),
    ]
    # Y una sola consulta por tabla, no una por renglón.
    assert db.consultas_origen == 1


def test_el_cliente_con_guion_en_el_nombre_llega_entero():
    """El motivo por el que el cliente viaja en su propio campo.

    Se intentó sacarlo de la `descripcion` y se rompe justo acá: en
    "Cobro deuda - Kiosco 24 - Sucursal Centro - Reposición" no hay forma de
    saber dónde termina el nombre y empieza el concepto, y en pantalla el
    cliente salía cortado ("Kiosco 24").
    """
    deuda_id = uuid.uuid4()
    caja = [_caja(fecha=date(2026, 7, 20), categoria=CajaCategoria.COBRO_DEUDA,
                  tipo=CajaTipo.INGRESO, monto="100.00",
                  detalle="Cobro deuda - Kiosco 24 - Sucursal Centro - Reposición",
                  referencia_tipo="deuda_simple_cobro", referencia_id=deuda_id)]
    deuda = DeudaSimple(id=deuda_id, fecha=date(2026, 4, 2))
    deuda.cliente = Cliente(id=uuid.uuid4(), nombre="Kiosco 24 - Sucursal Centro")
    db = FakeDB(caja, [], origenes={DeudaSimple: [deuda]})
    items = service.get_movimientos_unificados(db, DESDE, HASTA)
    assert items[0].origen_cliente == "Kiosco 24 - Sucursal Centro"
