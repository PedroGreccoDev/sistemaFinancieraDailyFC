"""Las frases que se le mandan al modelo de verdad.

El grueso de la sesión entra por `dispatch` con el intent ya resuelto, que es
rápido, gratis y reproducible. Lo que ese camino **no** prueba es lo único que
aporta el modelo: entender lo que el operador escribió. Eso se prueba acá, con
llamadas reales, y por eso son pocas y elegidas.

**No son frases al azar: son las que ya salieron mal.** Cada una está en el
prompt como una trampa explícita, y varias costaron plata mal cargada antes de
que el contrato las contemplara. Gastar cincuenta llamadas en las frases fáciles
no diría nada; gastarlas acá dice si el modelo sigue distinguiendo lo que hay
que distinguir.

El error de estas confusiones **no es simétrico** —leer un cobro como traspaso
mete un ingreso que nunca entró y además deja viva una deuda—, así que lo que se
verifica es el intent, no la respuesta.

Ver §Sesión de carga y §Bot.
"""

from __future__ import annotations

# (frase, intent esperado, por qué importa)
FRASES: tuple[tuple[str, str, str], ...] = (
    # ── La dirección de la deuda: quién le debe a quién ───────────────
    ("Le debo 500 mil a Cuello por el lote de dólares", "REGISTRAR_DEUDA",
     "el negocio debe: NO mueve la caja al anotarse"),
    ("Kiosco El Ñandú me debe 200 lucas de mercadería", "REGISTRAR_DEUDA_CLIENTE",
     "el cliente debe: asienta un EGRESO el día que se carga"),
    ("Fernando me prestó 500 lucas", "REGISTRAR_DEUDA",
     "la única deuda del negocio que hace ENTRAR plata (ingreso_caja)"),
    ("Le presté 300 mil a Juan en 6 cuotas", "NUEVO_PRESTAMO",
     "se dice casi igual que la anterior y la plata va para el otro lado"),

    # ── Las tres frases del cobro ─────────────────────────────────────
    ("Juan me pagó 500 lucas", "COBRAR_DEUDA_CLIENTE",
     "entra plata a la caja"),
    ("Le pagué 500 lucas a Pedro", "PAGAR_PASIVO",
     "sale plata: es la misma frase con 'a' adelante"),
    ("Juan le transfirió 500 mil a Pedro", "COMPENSAR_DEUDA",
     "no se mueve la caja; entre esta y la primera hay un 'a Pedro'"),

    # ── Traspaso contra cobro ─────────────────────────────────────────
    ("Deposité 500 mil en el banco", "TRASPASO_CAJA",
     "plata propia que cambia de caja: el neto del día no se mueve"),
    ("Juan me depositó 500 mil", "COBRAR_DEUDA_CLIENTE",
     "hay otra persona: entró plata al negocio"),
    ("Saqué 200 lucas del cajero", "TRASPASO_CAJA",
     "el traspaso al revés"),

    # ── Editar contra revertir ────────────────────────────────────────
    ("El porcentaje del cheque 12345 era 3 y no 2", "EDITAR_OPERACION",
     "corrige un valor mal cargado"),
    ("Borrá la venta del cheque 12345, no se vendió", "REVERTIR_OPERACION",
     "deshace la operación entera"),

    # ── Consultas: los dos lados de 'deudas' ──────────────────────────
    ("¿Cuánto debo?", "CONSULTA", "PASIVOS: lo que el negocio debe"),
    ("¿Quién me debe?", "CONSULTA", "DEUDORES: lo que le deben al negocio"),
    ("¿Cómo viene la caja hoy?", "CONSULTA", "CAJA del día"),
    ("¿Qué tengo en cartera?", "CONSULTA", "CARTERA"),

    # ── Lo que hay que preguntar en vez de asumir ─────────────────────
    ("Juan pagó", "ACLARACION_REQUERIDA",
     "sin importe no se cobra: dar por cobrada una cuota descuadra la caja"),
    ("Compré 1000 dólares", "ACLARACION_REQUERIDA",
     "la cotización NUNCA se asume"),
    ("Vendí el 12345", "ACLARACION_REQUERIDA",
     "sin el porcentaje de venta no se puede cargar"),

    # ── Operaciones normales, para que no sea todo trampa ─────────────
    ("Compré 1000 dólares a 1250", "MOVIMIENTO_EFECTIVO", "la compra de siempre"),
    ("Cargué 10.000 de nafta", "REGISTRAR_GASTO", "el gasto de siempre"),
    ("Vendí el cheque 12345 al 3% a Juan", "VENDER_CHEQUE", "la venta de siempre"),
    ("Le fié el cheque 6457 al 5% a Olivero", "FIAR_CHEQUE",
     "'fiar' acá es entregar un cheque, no prestar plata"),
    ("Le fié 200 mil a Olivero", "REGISTRAR_DEUDA_CLIENTE",
     "la misma palabra sin cheque de por medio es una deuda de cliente"),
)
