"""El bot paga las deudas del negocio y mueve plata entre las dos cajas.

Hasta acá el bot **anotaba** los pasivos pero no los pagaba: "le pagué 500 lucas
a Cuello" caía en DESCONOCIDO y el bot ni siquiera avisaba que había que ir al
panel. Lo que se custodia acá es que esa frase se distinga de las dos que se
dicen casi igual —"Juan me pagó" (entra plata) y "Juan le transfirió a Pedro"
(no se mueve nada)— y que el traspaso no se confunda con un cobro.

Estilo del proyecto: unitarios puros, sin BD.

Ver §Caja paralela y §5.
"""

from __future__ import annotations

import inspect
from decimal import Decimal

from app.db.models import MedioPago
from app.services.ia.contrato import INTENTS, _SYSTEM_PROMPT
from app.services import pasivos as svc_pasivos
from app.services.pasivos import _repartir_en_moneda_pago
from app.services.whatsapp import dispatcher


# ══════════════════════════════════════════════════════════════════════
#  Los intents existen y están cableados
# ══════════════════════════════════════════════════════════════════════

def test_pagar_pasivo_es_un_intent_valido() -> None:
    # Sin esto el modelo lo devuelve y el motor lo baja a DESCONOCIDO: el bot
    # contesta "no entendí" a una operación que sabe hacer.
    assert "PAGAR_PASIVO" in INTENTS
    assert "TRASPASO_CAJA" in INTENTS


def test_los_intents_estan_cableados_al_dispatcher() -> None:
    """Documentado en el prompt pero sin handler es peor que no existir: el
    operador pide algo válido y el bot le dice que no sabe hacerlo."""
    codigo = inspect.getsource(dispatcher)
    for intent, handler in (
        ("PAGAR_PASIVO", "_pagar_pasivo"),
        ("TRASPASO_CAJA", "_traspaso_caja"),
    ):
        assert f'"{intent}"' in codigo
        assert hasattr(dispatcher, handler)


def test_el_prompt_ensena_las_dos_operaciones() -> None:
    assert "PAGAR_PASIVO" in _SYSTEM_PROMPT
    assert "TRASPASO_CAJA" in _SYSTEM_PROMPT


# ══════════════════════════════════════════════════════════════════════
#  Las frases que se dicen casi igual
# ══════════════════════════════════════════════════════════════════════

def test_el_prompt_separa_pagar_de_cobrar_y_de_compensar() -> None:
    """Tres frases casi idénticas con tres sentidos de caja distintos.

    El error no es simétrico: leer "le pagué a Pedro" como "Pedro me pagó" mete
    un ingreso que nunca entró **y** deja viva la deuda con Pedro.
    """
    assert '"le pagué 500 lucas a Pedro"        → PAGAR_PASIVO' in _SYSTEM_PROMPT
    assert "COBRAR_DEUDA_CLIENTE (ENTRA plata a tu caja)" in _SYSTEM_PROMPT
    assert "COMPENSAR_DEUDA (NO se mueve la caja)" in _SYSTEM_PROMPT


def test_el_prompt_separa_el_deposito_del_cobro_por_transferencia() -> None:
    """"Deposité 500 mil" y "Juan me depositó 500 mil" se dicen casi igual.

    El primero es plata propia cambiando de bolsillo; el segundo es un ingreso
    real. Confundirlos infla o desinfla el neto del día por el monto entero.
    """
    seccion = _SYSTEM_PROMPT.split("TRASPASO_CAJA", 1)[1].split("MOVIMIENTO_EFECTIVO", 1)[0]
    assert "NO ES UN COBRO NI UN PAGO" in seccion
    assert "si hay **otra persona**" in seccion


# ══════════════════════════════════════════════════════════════════════
#  El medio nunca frena la operación
# ══════════════════════════════════════════════════════════════════════

def test_sin_medio_declarado_va_efectivo() -> None:
    """Es lo único que el bot asume, y es a propósito (regla 15).

    Preguntar "¿efectivo o transferencia?" en cada carga duplicaría cada mensaje,
    y una pregunta que se contesta siempre igual se termina apretando sin leer.
    """
    assert dispatcher._medio({}) == MedioPago.EFECTIVO
    assert dispatcher._medio({"medio_pago": None}) == MedioPago.EFECTIVO


def test_el_medio_declarado_se_respeta() -> None:
    assert dispatcher._medio({"medio_pago": "TRANSFERENCIA"}) == MedioPago.TRANSFERENCIA
    assert dispatcher._medio({"medio_pago": "transferencia"}) == MedioPago.TRANSFERENCIA


def test_un_medio_mal_escrito_no_tumba_la_operacion() -> None:
    """Cae en el caso normal en vez de tirar la carga entera por una palabra."""
    assert dispatcher._medio({"medio_pago": "BANCO"}) == MedioPago.EFECTIVO


def test_las_divisas_leen_los_dos_medios_por_separado() -> None:
    """Se transfieren los pesos y se reciben los billetes: dos cajas distintas."""
    data = {"medio_pago": "TRANSFERENCIA", "medio_usd": "EFECTIVO"}
    assert dispatcher._medio(data) == MedioPago.TRANSFERENCIA
    assert dispatcher._medio(data, "medio_usd") == MedioPago.EFECTIVO


# ══════════════════════════════════════════════════════════════════════
#  El reparto de un pago entre varias deudas del mismo acreedor
# ══════════════════════════════════════════════════════════════════════

def _partes(imputados: list[str], reduccion: str, pagado: str) -> list[Decimal]:
    return _repartir_en_moneda_pago(
        [Decimal(i) for i in imputados], Decimal(reduccion), Decimal(pagado)
    )


def test_el_reparto_en_la_moneda_de_pago_suma_exacto() -> None:
    """Cada deuda lleva su línea de caja y la suma tiene que dar lo que salió.

    Prorratear y redondear cada una dejaría la caja del día unos centavos
    corrida, que es exactamente el descuadre que nadie encuentra.
    """
    partes = _partes(["333.33", "333.33", "333.34"], "1000.00", "1000.00")
    assert sum(partes) == Decimal("1000.00")


def test_el_reparto_cross_moneda_tambien_cierra() -> None:
    """Pagar en dólares una deuda en pesos: las partes van en dólares."""
    partes = _partes(["700000.00", "300000.00"], "1000000.00", "1000.00")
    assert sum(partes) == Decimal("1000.00")
    assert partes[0] == Decimal("700.00")


def test_sin_reduccion_no_se_reparte_nada() -> None:
    """Un pago que no imputa contra nada no puede sacar plata de la caja."""
    assert _partes(["100.00"], "0.00", "0.00") == [Decimal("0.00")]


# ══════════════════════════════════════════════════════════════════════
#  Pagos que no saldan nada — hallados en la revisión del 2026-08-25
# ══════════════════════════════════════════════════════════════════════

def test_un_pago_que_no_baja_un_centavo_se_rechaza() -> None:
    """Contestar "listo" sin haber tocado la deuda es peor que fallar.

    Un importe que redondeado a centavos da cero —o una cotización que lo
    pulveriza— dejaba pasar la operación: el bot respondía el pago hecho, la
    deuda quedaba igual y de la caja no salía un peso. El operador se iba
    convencido de que pagó.
    """
    fuente = inspect.getsource(svc_pasivos.pagar_a_acreedor)
    assert "if reduccion <= _CERO:" in fuente
    assert "raise ValidationError" in fuente


def test_un_cheque_que_no_vale_nada_no_se_entrega() -> None:
    """Al 100% de descuento el neto es cero: saldaría nada y saldría de cartera.

    Es la peor forma de perder un cheque —sin error, sin deuda saldada y sin
    rastro de a dónde fue—, así que se rechaza antes de tocarlo.
    """
    fuente = inspect.getsource(svc_pasivos.cancelar_a_acreedor_con_cheque)
    assert "if valor_neto <= _CERO:" in fuente
    # La validación va ANTES de sacar el cheque de cartera.
    assert fuente.index("valor_neto <= _CERO") < fuente.index("transition_to")
