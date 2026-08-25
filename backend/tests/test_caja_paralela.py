"""Las dos cajas en paralelo: el efectivo del cajón y la plata del banco.

Lo que se custodia acá es que **ningún movimiento quede fuera de los dos
saldos** y que ninguno caiga en los dos. Es la clase de error que no da señal:
el neto del día sigue dando bien —la plata entró o salió igual— y el descuadre
solo aparece cuando alguien cuenta billetes y le sobran.

Estilo del proyecto: unitarios puros, sin BD.

Ver §Caja paralela.
"""

from __future__ import annotations

import inspect
import uuid
from decimal import Decimal

import pytest

from app.db.models import CajaCategoria, CajaTipo, MedioPago, Moneda, MovimientoCaja
from app.services import caja as svc_caja
from app.services import traspasos as svc_traspasos
from app.services.exceptions import ValidationError


# ══════════════════════════════════════════════════════════════════════
#  El medio es obligatorio: nada puede quedar fuera de las dos cajas
# ══════════════════════════════════════════════════════════════════════

def test_registrar_exige_medio_de_pago() -> None:
    """`caja.registrar` no tiene default para `medio_pago`, y es a propósito.

    Con un default, una operación nueva que se lo olvidara entraría igual y sus
    líneas irían todas al efectivo en silencio. Que sea obligatorio hace que el
    olvido falle en el momento de escribir el código y no en el cierre del mes.
    """
    firma = inspect.signature(svc_caja.registrar)
    medio = firma.parameters["medio_pago"]
    assert medio.default is inspect.Parameter.empty
    assert medio.kind is inspect.Parameter.KEYWORD_ONLY


def test_el_modelo_no_admite_medio_nulo() -> None:
    """Una línea sin medio no pertenecería a ninguno de los dos saldos."""
    columna = MovimientoCaja.__table__.c.medio_pago
    assert columna.nullable is False


def test_toda_operacion_de_caja_pasa_el_medio() -> None:
    """Ningún `caja.registrar()` del código puede omitir `medio_pago`.

    El chequeo es sobre el árbol de sintaxis y no sobre los tests de cada módulo:
    una llamada nueva sin medio revienta en runtime, pero recién el día que
    alguien ejecute esa rama — y puede ser en producción.
    """
    import ast
    import pathlib

    faltan = []
    raiz = pathlib.Path(inspect.getfile(svc_caja)).parents[1]
    for archivo in raiz.rglob("*.py"):
        arbol = ast.parse(archivo.read_text(encoding="utf-8"))
        for nodo in ast.walk(arbol):
            if not isinstance(nodo, ast.Call):
                continue
            nombre = getattr(nodo.func, "attr", None) or getattr(nodo.func, "id", None)
            if nombre != "registrar":
                continue
            claves = {k.arg for k in nodo.keywords}
            if "categoria" in claves and "medio_pago" not in claves:
                faltan.append(f"{archivo.name}:{nodo.lineno}")
    assert not faltan, f"registrar() sin medio_pago en: {faltan}"


# ══════════════════════════════════════════════════════════════════════
#  El medio no se pierde al rehacer una operación
# ══════════════════════════════════════════════════════════════════════

class _FakeQuery:
    def __init__(self, filas: list[MovimientoCaja]) -> None:
        self._filas = filas

    def filter(self, *_args, **_kwargs) -> "_FakeQuery":
        return self

    def order_by(self, *_args) -> "_FakeQuery":
        return self

    def first(self) -> MovimientoCaja | None:
        return self._filas[0] if self._filas else None


class _FakeDB:
    def __init__(self, filas: list[MovimientoCaja]) -> None:
        self._filas = filas

    def query(self, *_args) -> _FakeQuery:
        return _FakeQuery(self._filas)


def _linea(medio: MedioPago, moneda: Moneda = Moneda.ARS) -> MovimientoCaja:
    return MovimientoCaja(
        id=uuid.uuid4(),
        moneda=moneda,
        tipo=CajaTipo.EGRESO,
        categoria=CajaCategoria.GASTO,
        monto=Decimal("1000.00"),
        medio_pago=medio,
    )


def test_el_resync_conserva_el_medio_anterior() -> None:
    """Corregir el monto de un gasto pagado por transferencia no lo pasa a efectivo.

    Si lo hiciera, el error sería **doble**: la caja de efectivo baja de más y la
    del banco queda alta por lo mismo. Dos descuadres de un solo cambio.
    """
    db = _FakeDB([_linea(MedioPago.TRANSFERENCIA)])
    assert (
        svc_caja.medio_de_referencia(db, "gasto", uuid.uuid4(), CajaCategoria.GASTO)
        == MedioPago.TRANSFERENCIA
    )


def test_sin_linea_previa_el_medio_cae_en_efectivo() -> None:
    """Una operación que recién empieza a asentar caja arranca en el caso normal."""
    db = _FakeDB([])
    assert (
        svc_caja.medio_de_referencia(db, "gasto", uuid.uuid4(), CajaCategoria.GASTO)
        == MedioPago.EFECTIVO
    )


def test_medio_de_referencia_acepta_filtrar_por_moneda() -> None:
    """Una compra de dólares asienta DOS líneas de la misma categoría.

    Una saca pesos y la otra mete USD, y cada pata pudo ir por una caja distinta
    ("le transferí los pesos y me dio los billetes"). Sin el filtro por moneda,
    rehacer la operación leería el medio de la primera y lo aplicaría a las dos.
    """
    firma = inspect.signature(svc_caja.medio_de_referencia)
    assert "moneda" in firma.parameters


# ══════════════════════════════════════════════════════════════════════
#  Traspaso: lo único que cruza de una caja a la otra
# ══════════════════════════════════════════════════════════════════════

def test_el_traspaso_exige_cajas_distintas() -> None:
    """Mover plata dentro de la misma caja no es nada, y taparlo sería peor.

    Si se aceptara, se asentarían un ingreso y un egreso del mismo monto en el
    mismo saldo: se cancelan, así que no rompe nada — pero deja dos líneas
    inventadas en el libro que alguien va a tener que explicar.
    """
    with pytest.raises(ValidationError):
        svc_traspasos.registrar(
            None,
            monto=Decimal("1000"),
            origen=MedioPago.EFECTIVO,
            destino=MedioPago.EFECTIVO,
        )


def test_el_detalle_nombra_la_operacion_segun_el_sentido() -> None:
    """Depositar y extraer son la misma operación al revés; el texto lo dice."""
    assert (
        svc_traspasos._detalle_default(MedioPago.EFECTIVO, MedioPago.TRANSFERENCIA)
        == "Depósito en cuenta"
    )
    assert (
        svc_traspasos._detalle_default(MedioPago.TRANSFERENCIA, MedioPago.EFECTIVO)
        == "Extracción de la cuenta"
    )


def test_un_traspaso_a_medias_no_se_lista() -> None:
    """Sin sus dos líneas no es un traspaso: se saltea en vez de inventar el lado
    que falta, que mostraría una caja moviéndose sola."""
    fuente = inspect.getsource(svc_traspasos.listar)
    assert "if salida is None or entrada is None:" in fuente
    assert "continue" in fuente
