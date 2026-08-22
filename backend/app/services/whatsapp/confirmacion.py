"""Cuándo el sistema EXIGE confirmación, más allá de lo que decida el modelo.

El prompt ya le pide al modelo que pregunte antes de cargar una operación grande
(regla 10). Eso funciona casi siempre y además redacta mejor el mensaje, porque
el modelo sabe describir lo que está por hacer. Pero es una **instrucción**, no
una garantía: el día que el modelo la pasa por alto, una operación de tres
millones entra sin que nadie la haya visto, y eso no deja rastro en ningún lado
— el bot contesta "listo" y sigue.

Este módulo es la red por debajo: mira el monto **antes** del dispatch y fuerza
la confirmación si hace falta, diga lo que diga el modelo. No lo reemplaza, lo
respalda.

**Cómo encuentra el monto.** Recorre el `data` del intent buscando cualquier
clave de plata, incluso anidada en listas (`cheques[]`, `ventas[]`), y se queda
con **la mayor**. Es a propósito que sea un barrido genérico y no una regla por
intent: un intent nuevo quedaría sin proteger, en silencio, hasta que alguien se
acordara de darlo de alta. Así entra cubierto solo. El precio es algún falso
positivo —pedir confirmación de más—, que cuesta un "dale" y no plata mal
cargada.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Claves que representan **el tamaño de la operación**.
_CLAVES_PLATA = ("monto", "importe", "credito", "total_a_cobrar")

# Números que NO son el tamaño de la operación y que colarían falsos positivos:
# una cotización de 1.250 no dice nada del monto, y `monto_abonado` es siempre
# una parte del total —que ya se está mirando— pero puede venir en la otra
# moneda (USD comprados, pesos abonados) y confundir la comparación.
_CLAVES_IGNORADAS = (
    "cotizacion",
    "monto_abonado",
    "numero_cuota",
    "cantidad_cuotas",
    "porcentaje",
)


def _es_clave_de_plata(clave: str) -> bool:
    baja = clave.lower()
    if any(ign in baja for ign in _CLAVES_IGNORADAS):
        return False
    return any(pista in baja for pista in _CLAVES_PLATA)


def monto_en_juego(data: Any, moneda_heredada: str = "ARS") -> tuple[float, str]:
    """Mayor monto encontrado en el `data` de un intent, con su moneda.

    La moneda se hereda hacia abajo: en `{"moneda": "USD", "ventas": [{"monto":
    900}]}` esos 900 son dólares aunque el monto no lo diga. Devuelve
    `(0.0, moneda)` si no hay ningún monto reconocible — hay operaciones que no
    mueven plata (rechazar un cheque, corregir un dato) y ahí no hay nada que
    comparar contra un umbral.
    """
    if isinstance(data, dict):
        moneda = str(data.get("moneda") or moneda_heredada).strip().upper() or moneda_heredada
        mayor, moneda_mayor = 0.0, moneda
        for clave, valor in data.items():
            if isinstance(valor, (dict, list)):
                anidado, moneda_anidada = monto_en_juego(valor, moneda)
                if anidado > mayor:
                    mayor, moneda_mayor = anidado, moneda_anidada
            elif _es_clave_de_plata(clave) and isinstance(valor, (int, float)):
                # `bool` es subclase de `int`: un True colado sería un monto de 1.
                if not isinstance(valor, bool) and float(valor) > mayor:
                    mayor, moneda_mayor = float(valor), moneda
        return mayor, moneda_mayor

    if isinstance(data, list):
        mayor, moneda_mayor = 0.0, moneda_heredada
        for item in data:
            anidado, moneda_anidada = monto_en_juego(item, moneda_heredada)
            if anidado > mayor:
                mayor, moneda_mayor = anidado, moneda_anidada
        return mayor, moneda_mayor

    return 0.0, moneda_heredada


def exige_confirmacion(
    intent_result: Any,
    umbral_ars: float,
    umbral_usd: float,
) -> tuple[bool, float, str]:
    """¿Esta operación tiene que confirmarse sí o sí?

    Devuelve `(hace_falta, monto, moneda)` — el monto y la moneda salen para el
    log, que es lo que después permite entender por qué el bot preguntó.

    Solo aplica a operaciones de **escritura**: una consulta no mueve plata y
    hacerla confirmar sería ruido puro.
    """
    if not intent_result.is_write_operation():
        return False, 0.0, "ARS"

    monto, moneda = monto_en_juego(getattr(intent_result, "data", {}) or {})
    if monto <= 0:
        return False, monto, moneda

    umbral = umbral_usd if moneda == "USD" else umbral_ars
    return monto >= umbral, monto, moneda


def con_pregunta(texto: str) -> str:
    """Se asegura de que el mensaje pida una respuesta.

    Cuando la confirmación la fuerza el sistema, el modelo escribió su mensaje
    creyendo que la operación se ejecutaba: describe lo que hizo, no lo que va a
    hacer. Sin esto el operador recibe un resumen sin saber que del otro lado
    quedó algo esperando su "dale" — y la operación se queda colgada.
    """
    limpio = (texto or "").strip()
    if not limpio:
        return "¿Confirmás esta operación?"
    if "?" in limpio or "¿" in limpio:
        return limpio
    return f"{limpio}\n\n¿Confirmás?"
