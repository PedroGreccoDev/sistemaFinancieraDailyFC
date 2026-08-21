"""Consultas del bot: un intent genérico con `tipo` y `periodo` (§Bot).

Hasta 2026-08-21 el bot sabía contestar tres preguntas (cartera, cliente,
préstamos). Ahora contesta once, y el contrato pasó a ser un solo intent
`CONSULTA` con un `tipo` adentro. Eso concentra dos riesgos que estos tests
custodian:

1. **El catálogo se desincroniza.** El prompt enseña un tipo, el dispatcher no lo
   tiene ruteado (o al revés) y el operador pregunta algo que el bot dice no
   entender —o peor, que entiende y no contesta—. No da error en ningún lado.
2. **El período lo resuelve el sistema, no el modelo.** El system prompt está
   cacheado por prefijo y no puede llevar la fecha de hoy adentro, así que
   "esta semana" llega como una palabra y se convierte acá. Si esa conversión se
   corre un día, el reporte que lee el operador es de otro período y no tiene
   cómo notarlo.

Estilo del proyecto: unitarios puros sobre el contrato del prompt y del
dispatcher, sin llamar al modelo ni tocar la BD.
"""

from __future__ import annotations

import inspect
import re
from datetime import date
from decimal import Decimal

import pytest

from app.db.models import Cheque, Moneda
from app.services.ia.claude import INTENTS, IntentResult, _SYSTEM_PROMPT, contexto_fecha
from app.services.whatsapp import dispatcher
from app.services.whatsapp.dispatcher import (
    _CONSULTAS,
    _CONSULTAS_LEGACY,
    _detalle,
    _etiqueta_periodo,
    _monto,
    _neto_compra,
    _resolver_periodo,
    _totales_por_moneda,
)
from app.services.exceptions import ValidationError


# ── El intent existe de punta a punta ─────────────────────────────────

def test_consulta_es_un_intent_valido() -> None:
    # Si no está en la lista blanca, el parser lo baja a DESCONOCIDO y el bot
    # responde "no entendí" a cualquier pregunta.
    assert "CONSULTA" in INTENTS


def test_el_handler_esta_conectado_al_intent() -> None:
    codigo = inspect.getsource(dispatcher.dispatch)
    assert '"CONSULTA"' in codigo
    assert "_consulta(db, data)" in codigo


def test_una_consulta_no_escribe_en_la_base() -> None:
    # `is_write_operation` decide si la sesión se limpia y si la operación pide
    # confirmación. Una consulta marcada como escritura pediría confirmar para
    # mostrar un saldo.
    assert not IntentResult(intent="CONSULTA").is_write_operation()


# ── El catálogo del prompt y el del dispatcher son el mismo ───────────

def _tipos_del_prompt() -> set[str]:
    """Los tipos que el prompt le enseña al modelo, leídos del propio prompt."""
    bloque = _SYSTEM_PROMPT.split("- tipo: qué quiere ver")[1].split("- periodo:")[0]
    return set(re.findall(r"\*\s+([A-Z]+)\s+→", bloque))


def test_todo_tipo_que_el_prompt_ensena_tiene_handler() -> None:
    # El modelo devuelve un tipo que el dispatcher no conoce → el operador
    # pregunta algo perfectamente válido y el bot le contesta "no sé qué
    # consultar". Nada falla; solo no anda.
    faltan = _tipos_del_prompt() - set(_CONSULTAS)
    assert not faltan, f"El prompt enseña tipos sin handler: {sorted(faltan)}"


def test_todo_handler_esta_documentado_en_el_prompt() -> None:
    # Al revés: un handler que el prompt no menciona es código muerto, porque el
    # modelo nunca va a pedir ese tipo.
    faltan = set(_CONSULTAS) - _tipos_del_prompt()
    assert not faltan, f"Hay handlers que el prompt no enseña: {sorted(faltan)}"


def test_los_intents_viejos_siguen_ruteando() -> None:
    # Una sesión abierta arrastra historial con el contrato anterior. Sin el
    # alias, el bot deja de contestar a mitad de conversación.
    assert _CONSULTAS_LEGACY == {
        "CONSULTA_CARTERA": "CARTERA",
        "CONSULTA_CLIENTE": "CLIENTE",
        "CONSULTA_PRESTAMOS": "PRESTAMOS",
    }
    for intent, tipo in _CONSULTAS_LEGACY.items():
        assert tipo in _CONSULTAS
        assert intent in INTENTS
        assert not IntentResult(intent=intent).is_write_operation()


# ── Períodos: los resuelve el sistema, no el modelo ───────────────────

_VIERNES = date(2026, 8, 21)


def test_hoy_y_ayer() -> None:
    assert _resolver_periodo({"periodo": "HOY"}, hoy=_VIERNES) == ("HOY", _VIERNES, _VIERNES)
    ayer = date(2026, 8, 20)
    assert _resolver_periodo({"periodo": "AYER"}, hoy=_VIERNES) == ("AYER", ayer, ayer)


def test_la_semana_arranca_el_lunes() -> None:
    # De lunes a hoy, no los últimos siete días: el operador pregunta por la
    # semana en curso.
    _, desde, hasta = _resolver_periodo({"periodo": "SEMANA"}, hoy=_VIERNES)
    assert desde == date(2026, 8, 17)  # lunes de esa semana
    assert desde.weekday() == 0
    assert hasta == _VIERNES


def test_un_lunes_la_semana_es_ese_mismo_dia() -> None:
    lunes = date(2026, 8, 17)
    assert _resolver_periodo({"periodo": "SEMANA"}, hoy=lunes) == ("SEMANA", lunes, lunes)


def test_el_mes_arranca_el_dia_uno() -> None:
    _, desde, hasta = _resolver_periodo({"periodo": "MES"}, hoy=_VIERNES)
    assert desde == date(2026, 8, 1)
    assert hasta == _VIERNES


def test_el_rango_usa_las_fechas_del_operador() -> None:
    periodo, desde, hasta = _resolver_periodo(
        {"periodo": "RANGO", "desde": "2026-08-01", "hasta": "2026-08-15"}, hoy=_VIERNES
    )
    assert (periodo, desde, hasta) == ("RANGO", date(2026, 8, 1), date(2026, 8, 15))


def test_el_rango_sin_hasta_llega_hasta_hoy() -> None:
    _, desde, hasta = _resolver_periodo(
        {"periodo": "RANGO", "desde": "2026-08-01"}, hoy=_VIERNES
    )
    assert (desde, hasta) == (date(2026, 8, 1), _VIERNES)


def test_el_rango_sin_desde_pregunta_en_vez_de_inventar() -> None:
    # Sin fecha de inicio no hay rango. Asumir una devolvería un reporte de un
    # período que el operador no pidió, con pinta de correcto.
    with pytest.raises(ValidationError):
        _resolver_periodo({"periodo": "RANGO", "hasta": "2026-08-15"}, hoy=_VIERNES)


def test_el_rango_al_reves_se_rechaza() -> None:
    with pytest.raises(ValidationError):
        _resolver_periodo(
            {"periodo": "RANGO", "desde": "2026-08-15", "hasta": "2026-08-01"}, hoy=_VIERNES
        )


def test_default_de_flujo_es_hoy_y_de_stock_es_todo() -> None:
    # "Movimientos" a secas son los de hoy; "cartera" a secas es toda la cartera.
    # Al revés, preguntar por los movimientos traería la historia entera.
    assert _resolver_periodo({"tipo": "MOVIMIENTOS"}, hoy=_VIERNES)[0] == "HOY"
    assert _resolver_periodo({"tipo": "CAJA"}, hoy=_VIERNES)[0] == "HOY"
    assert _resolver_periodo({"tipo": "CARTERA"}, hoy=_VIERNES)[0] == "TODO"
    assert _resolver_periodo({"tipo": "PASIVOS"}, hoy=_VIERNES)[0] == "TODO"


def test_un_periodo_que_el_modelo_invente_no_rompe() -> None:
    periodo, desde, hasta = _resolver_periodo({"periodo": "TRIMESTRE"}, hoy=_VIERNES)
    assert periodo == "TODO"
    assert desde < hasta == _VIERNES


def test_la_etiqueta_nombra_el_periodo_que_se_consultó() -> None:
    # El encabezado es lo único que le dice al operador qué período está mirando.
    assert _etiqueta_periodo("HOY", _VIERNES, _VIERNES) == "hoy (21/08/26)"
    assert "17/08/26" in _etiqueta_periodo("SEMANA", date(2026, 8, 17), _VIERNES)
    assert _etiqueta_periodo("TODO", date(2000, 1, 1), _VIERNES) == "histórico"


# ── La fecha va en el mensaje, NO en el system prompt ─────────────────

def test_el_system_prompt_no_lleva_la_fecha() -> None:
    # El system se cachea por coincidencia de prefijo: una fecha adentro tiraría
    # el caché en cada cambio de día, sin dar error y cobrando la entrada entera.
    assert "Hoy es" not in _SYSTEM_PROMPT
    assert str(date.today().year) not in _SYSTEM_PROMPT


def test_el_contexto_de_fecha_trae_el_dia_y_la_fecha() -> None:
    assert contexto_fecha(_VIERNES) == "(Hoy es viernes 2026-08-21.)"


def test_el_prompt_manda_a_usar_esa_fecha_para_los_rangos() -> None:
    # Sin esta instrucción el modelo resuelve "del 5 al 10" con el año que
    # suponga y la consulta vuelve vacía.
    assert "la fecha de hoy al principio" in _SYSTEM_PROMPT


# ── La ambigüedad que sí importa: quién le debe a quién ───────────────

def test_el_prompt_separa_lo_que_debo_de_lo_que_me_deben() -> None:
    # "Las deudas" en este negocio son dos cosas opuestas (§Reglas de código:
    # Pasivos vs Deudores). Contestar el lado equivocado le da al operador un
    # número que parece el suyo y no lo es.
    assert "PASIVOS" in _SYSTEM_PROMPT
    assert "DEUDORES" in _SYSTEM_PROMPT
    assert "A SECAS ES AMBIGUO" in _SYSTEM_PROMPT


def test_los_dos_lados_tienen_handlers_distintos() -> None:
    assert _CONSULTAS["PASIVOS"] is not _CONSULTAS["DEUDORES"]


# ── Formato de las respuestas ─────────────────────────────────────────

def test_el_detalle_se_corta_y_avisa_cuanto_quedo_afuera() -> None:
    # Un mes de movimientos no entra en un mensaje de WhatsApp. Cortar en
    # silencio haría leer "esto es todo" cuando no lo es.
    lineas = [f"linea {i}" for i in range(30)]
    salida = _detalle(lineas, limite=5)
    assert salida[:5] == lineas[:5]
    assert salida[-1].startswith("… y 25 más")


def test_el_detalle_corto_pasa_entero_y_sin_pie() -> None:
    lineas = ["a", "b"]
    assert _detalle(lineas, limite=5) == lineas


def test_las_monedas_no_se_suman_entre_si() -> None:
    # ARS y USD son cajas distintas (§7): un total único sería un número que no
    # existe.
    salida = _totales_por_moneda({Moneda.ARS: Decimal("1000"), Moneda.USD: Decimal("50")})
    assert salida == "$1.000,00 | U$D50,00"
    assert _totales_por_moneda({}) == "$0,00"
    assert _monto(Decimal("1500.5"), Moneda.USD) == "U$D1.500,50"


def test_el_neto_de_compra_descuenta_el_porcentaje() -> None:
    # Es la misma cuenta que hace el panel en Cartera.tsx: un cheque de
    # $1.000.000 al 10% se compró por $900.000. Si los dos lados divergen, el
    # bot y la pantalla muestran dos valores para la misma cartera.
    cheque = Cheque(monto=Decimal("1000000.00"), porcentaje_compra=Decimal("10"))
    assert _neto_compra(cheque) == Decimal("900000.00")


def test_un_cheque_sin_descuento_vale_su_nominal() -> None:
    cheque = Cheque(monto=Decimal("500000.00"), porcentaje_compra=Decimal("0"))
    assert _neto_compra(cheque) == Decimal("500000.00")
