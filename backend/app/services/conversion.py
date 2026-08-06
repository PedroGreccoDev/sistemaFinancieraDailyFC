"""conversion.py — Conversión de monedas para pagos de deudas.

Helper puro (sin BD) que comparten los módulos donde un pago puede hacerse en
una moneda distinta a la de la deuda: pasivos (deudas del negocio), fiados y
préstamos (deudas de clientes). Se testea en el estilo de `tests/` sin fixtures.
"""

from __future__ import annotations

from decimal import Decimal

from app.db.models import Moneda
from app.services.exceptions import ValidationError


def convertir_a_moneda_deuda(
    moneda_deuda: Moneda,
    moneda_pago: Moneda,
    monto_pagado: Decimal,
    cotizacion: Decimal | None,
) -> Decimal:
    """Convierte un monto a la moneda de la deuda, **sin topearlo al saldo**.

    Es la mitad "conversión" de `calcular_reduccion_saldo`, sin su validación de
    exceso. La usan los cobros con **cheque**, donde el valor del instrumento es
    fijo: si el cheque vale más que la deuda no se puede entregar de menos — la
    deuda queda saldada y el negocio le queda debiendo la diferencia al cliente
    (mismo criterio que fiados, §2, y que el vuelto de pasivos, §5).

    Para pagos en efectivo usá `calcular_reduccion_saldo`: ahí sí corresponde
    rechazar un pago mayor al saldo, porque se cobra exactamente lo que se debe.
    """
    if moneda_pago == moneda_deuda:
        return monto_pagado.quantize(Decimal("0.01"))
    if cotizacion is None or cotizacion <= Decimal("0"):
        raise ValidationError(
            "El pago es en una moneda distinta a la deuda: indicá la cotización "
            "(pesos por 1 USD)."
        )
    if moneda_deuda == Moneda.USD and moneda_pago == Moneda.ARS:
        convertido = monto_pagado / cotizacion
    else:  # deuda ARS, pago USD
        convertido = monto_pagado * cotizacion
    return convertido.quantize(Decimal("0.01"))


def calcular_reduccion_saldo(
    moneda_deuda: Moneda,
    saldo_pendiente: Decimal,
    moneda_pago: Moneda,
    monto_pagado: Decimal,
    cotizacion: Decimal | None,
) -> Decimal:
    """Cuánto baja el saldo de la deuda (en su moneda) por un pago.

    El operador paga `monto_pagado` en `moneda_pago` (lo que sale/entra en caja).
    Si la moneda de pago coincide con la de la deuda, la reducción es directa. Si
    difiere, se convierte con la cotización (pesos por 1 USD): deuda USD pagada en
    ARS → `monto/cotizacion`; deuda ARS pagada en USD → `monto*cotizacion`.

    Lanza ValidationError si falta la cotización en un pago cross-moneda o si el
    pago supera el saldo (con tolerancia de 1 centavo por redondeo de conversión).
    """
    if moneda_pago == moneda_deuda:
        reduccion = monto_pagado
    else:
        if cotizacion is None or cotizacion <= Decimal("0"):
            raise ValidationError(
                "El pago es en una moneda distinta a la deuda: indicá la cotización "
                "(pesos por 1 USD)."
            )
        if moneda_deuda == Moneda.USD and moneda_pago == Moneda.ARS:
            reduccion = monto_pagado / cotizacion
        else:  # deuda ARS, pago USD
            reduccion = monto_pagado * cotizacion

    reduccion = reduccion.quantize(Decimal("0.01"))
    exceso = reduccion - saldo_pendiente
    # Tolerancia de redondeo: un exceso de hasta un centavo (por convertir de moneda)
    # se trata como cancelación exacta, para que pagar "el total" no falle ni deje resto.
    if exceso > Decimal("0.01"):
        raise ValidationError(
            f"El pago equivale a {reduccion} {moneda_deuda.value} y supera el saldo "
            f"pendiente ({saldo_pendiente} {moneda_deuda.value})."
        )
    if exceso > Decimal("0"):
        return saldo_pendiente.quantize(Decimal("0.01"))
    return reduccion
