"""Detección del monto de una operación, para exigir confirmación (§Bot).

Unitario puro sobre funciones sin BD ni red. Lo que se custodia es que el
barrido encuentre la plata **donde sea que esté** —incluso anidada en listas— y
que no confunda con un monto a los números que no lo son.
"""

from __future__ import annotations

from app.services.ia.contrato import IntentResult
from app.services.whatsapp import confirmacion as c

UMBRAL_ARS = 700_000
UMBRAL_USD = 500


def _intent(intent: str, data: dict) -> IntentResult:
    return IntentResult(intent=intent, data=data)


# ── Encontrar el monto ─────────────────────────────────────────────────

def test_encuentra_el_monto_suelto() -> None:
    assert c.monto_en_juego({"monto": 12_345}) == (12_345.0, "ARS")


def test_encuentra_el_mayor_dentro_de_una_lista() -> None:
    """Una foto con varios cheques manda un array: el que decide es el más
    grande, no el primero."""
    data = {"cheques": [{"monto": 100_000}, {"monto": 900_000}, {"monto": 50_000}]}
    assert c.monto_en_juego(data) == (900_000.0, "ARS")


def test_la_moneda_se_hereda_hacia_abajo() -> None:
    """En `{"moneda": "USD", "ventas": [{"monto": 900}]}` esos 900 son dólares
    aunque el monto no lo diga."""
    data = {"moneda": "USD", "ventas": [{"monto": 900}]}
    assert c.monto_en_juego(data) == (900.0, "USD")


def test_la_cotizacion_no_es_un_monto() -> None:
    """1.250 pesos por dólar no dice nada del tamaño de la operación. Contarla
    haría que cada operación en dólares pidiera confirmación."""
    monto, _ = c.monto_en_juego({"monto": 100, "cotizacion_aplicada": 1250})
    assert monto == 100.0


def test_los_numeros_que_no_son_plata_no_cuentan() -> None:
    data = {"numero_cuota": 3, "cantidad_cuotas": 12, "porcentaje_compra": 5}
    assert c.monto_en_juego(data) == (0.0, "ARS")


def test_un_booleano_no_es_un_monto() -> None:
    """`bool` es subclase de `int` en Python: un True colado sería un monto de 1
    y arrastraría la moneda equivocada."""
    assert c.monto_en_juego({"monto_confirmado": True}) == (0.0, "ARS")


def test_sin_montos_no_hay_nada_que_comparar() -> None:
    """Rechazar un cheque o corregir un dato no mueve plata."""
    assert c.monto_en_juego({"nro_cheque": "4500", "motivo": "sin fondos"}) == (0.0, "ARS")


# ── Decidir si hace falta confirmar ────────────────────────────────────

def test_exige_confirmacion_arriba_del_umbral() -> None:
    hace_falta, monto, moneda = c.exige_confirmacion(
        _intent("VENDER_CHEQUE", {"ventas": [{"monto": 3_000_000}]}), UMBRAL_ARS, UMBRAL_USD
    )
    assert hace_falta and monto == 3_000_000 and moneda == "ARS"


def test_en_el_umbral_exacto_tambien_confirma() -> None:
    hace_falta, _, _ = c.exige_confirmacion(
        _intent("REGISTRAR_GASTO", {"monto": UMBRAL_ARS}), UMBRAL_ARS, UMBRAL_USD
    )
    assert hace_falta


def test_no_molesta_por_debajo() -> None:
    hace_falta, _, _ = c.exige_confirmacion(
        _intent("REGISTRAR_GASTO", {"monto": 8_000}), UMBRAL_ARS, UMBRAL_USD
    )
    assert not hace_falta


def test_los_dolares_van_contra_su_propio_umbral() -> None:
    """900 no es grande en pesos; 900 dólares sí."""
    hace_falta, _, moneda = c.exige_confirmacion(
        _intent("MOVIMIENTO_EFECTIVO", {"moneda": "USD", "monto": 900}), UMBRAL_ARS, UMBRAL_USD
    )
    assert hace_falta and moneda == "USD"


def test_una_consulta_nunca_pide_confirmacion() -> None:
    """No toca nada: hacerla confirmar es ruido puro, y el ruido enseña a
    apretar "dale" sin leer."""
    hace_falta, _, _ = c.exige_confirmacion(
        _intent("CONSULTA", {"tipo": "CAJA", "monto": 9_000_000}), UMBRAL_ARS, UMBRAL_USD
    )
    assert not hace_falta


def test_un_intent_nuevo_queda_cubierto_solo() -> None:
    """El barrido es genérico a propósito: una regla por intent dejaría a los
    que se agreguen mañana sin proteger, en silencio."""
    hace_falta, _, _ = c.exige_confirmacion(
        _intent("VENDER_CHEQUE", {"campo_que_no_existe_hoy": {"importe": 5_000_000}}),
        UMBRAL_ARS,
        UMBRAL_USD,
    )
    assert hace_falta


# ── El mensaje tiene que pedir respuesta ───────────────────────────────

def test_le_agrega_la_pregunta_al_mensaje() -> None:
    """El modelo lo escribió creyendo que la operación se ejecutaba: describe lo
    hecho, no lo que va a hacer."""
    assert c.con_pregunta("Vendí el 4500 al 3%").endswith("¿Confirmás?")


def test_no_repite_la_pregunta_si_ya_estaba() -> None:
    texto = "Vendo el 4500 al 3%. ¿Confirmás?"
    assert c.con_pregunta(texto) == texto


def test_un_mensaje_vacio_igual_pide_confirmacion() -> None:
    assert c.con_pregunta("") == "¿Confirmás esta operación?"
