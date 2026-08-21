# Cómo usar el bot — Financiera Daily FC

Hablale por WhatsApp como le hablarías a un compañero. No hay comandos ni formatos raros.

Podés **escribirle, mandarle un audio o una foto**. Los audios los entiende igual que el
texto: si tenés las manos ocupadas, dictáselo.

Solo funciona desde el teléfono habilitado y en el chat del bot. Desde otro número no
contesta, y en grupos tampoco.

⚠️ **Ese teléfono es la llave del sistema.** Desde ahí se carga y se borra plata. No pases
el número del bot ni le prestes el celular a nadie: si otra persona necesita cargar
operaciones, se pide el alta al administrador.

---

## Las 4 reglas

**1. Siempre leé la respuesta.**

- ✅ 💸 📋 → quedó cargado.
- ⚠️ ❓ ⛔ → **no se cargó nada**.

**2. Una cosa por vez.** Mandá la operación, esperá la respuesta, recién ahí seguí.

**3. Cargá en el momento.** El sistema usa la fecha del mensaje. Lo que cargues hoy queda
como si hubiera pasado hoy, aunque sea de ayer.

**4. Si el bot te pregunta algo, contestale eso.** Si le mandás otra cosa, se cancela la
operación anterior.

---

## Hablale en criollo

No hace falta que le dictes números redondos ni que hables "técnico". Entiende cómo se
habla de la plata acá:

| Si decís | Entiende |
|---|---|
| luca | 1.000 — "dos lucas" = 2.000 · "luca y media" = 1.500 |
| milqui | 1.500 — dosqui = 2.500 · tresqui = 3.500 |
| gamba | 100 |
| palo | 1.000.000 — "medio palo" = 500.000 |
| palo verde | 1.000.000 dólares |
| mango, peso | la unidad |
| 10 mil · 10mil · 10k | 10.000 |

Todo se entiende en pesos salvo que digas **"dólares", "USD" o "verdes"**.

Y si usás un modismo que no conoce, **te pregunta en vez de adivinar**. Que pregunte es
bueno: es plata.

---

## Qué le podés decir

### Cheques

| Decís | Hace |
|---|---|
| *(foto)* + "al 8%" | Carga el cheque en cartera |
| *(foto de varios)* + "son 4 al 8%" | Carga los 4 |
| "Vendí el 4581 al 3% a Gómez" | Registra la venta y te dice la ganancia |
| "Se lo fié a Juan Pérez al 3%" | Queda como deuda abierta de Juan |
| "Cobré el 4581" | Marca cobrado en ventanilla |
| "Rebotó el 4581" | Marca rechazado |

**El porcentaje se lo tenés que decir vos.** No está impreso en el cheque.

**Cuando cargás varios de una foto, te los lista y pide confirmar. Revisá esa lista:**
número, banco y monto de cada uno. Es la única forma de darte cuenta si leyó mal un
número — el bot no puede saberlo solo. Si uno falla (por ejemplo, porque ya estaba
cargado), los demás se cargan igual y te dice cuál falló: no hace falta sacar la foto de
nuevo.

Si te pide el banco, es porque hay dos cheques con el mismo número. Decíle cuál:
*"el del Santander"*.

Podés nombrar el cheque con los últimos números: **"el 681"** encuentra el 03789681.

### Plata que entra

| Decís | Hace |
|---|---|
| "Kiosco me entregó 200 lucas" | Baja **todo lo que debe**, de lo más viejo a lo más nuevo |
| "Cobré 50 mil a Pedrón" | Lo mismo: no hace falta decir contra qué deuda va |
| "Juan pagó" | **Te pregunta cuánto te dio** — sin el monto no cobra |
| "Pedro pagó la 3" | Cobra esa cuota |
| "María abonó 2 cuotas" | Cobra dos |
| "Juan me pagó $50.000 del fiado" | Cobra el fiado (acepta pagos parciales) |
| "Juan me trajo el cheque 9988 de $100.000 al 2% para el fiado" | Entra el cheque y salda el fiado |

**Cuando el cliente te entrega plata y no aclarás contra qué, el bot le baja lo que
debe empezando por lo más viejo** — le da igual si eso es un cheque que le fiaste, una
deuda común o una cuota de un préstamo. Después te contesta qué quedó saldado, así lo
ves en el momento. Si querés que vaya a una deuda puntual, nombrala ("la cuota", "el
fiado"). Y si el cliente te debe en pesos **y** en dólares, te pregunta contra cuál va.

**Decile siempre cuánta plata te dieron.** Si escribís "Juan pagó" a secas, el bot te
pregunta el monto en vez de cobrar. Es a propósito: el cliente entrega lo que tiene, y
dar por cobrada una cuota entera cuando te dieron la mitad te descuadra la caja del día.

⚠️ **"Me entregó" y "me debe" son cosas opuestas**, aunque suenen igual:

- *"Kiosco me entregó 200 lucas"* → te **trajo** plata: la cobra y **entra** a la caja.
- *"Kiosco me debe 200 lucas"* → le **diste** plata: la anota como deuda y **sale** de la caja.

Mismo cliente, mismo monto, y la caja del día se va al doble para el lado equivocado. Si el
bot no entiende para qué lado va, te pregunta.

### Cuando un cliente le paga a alguien a quien vos le debés

| Decís | Hace |
|---|---|
| "Juan le transfirió 500 lucas a Pedro" | Baja lo que Juan te debe **y** lo que vos le debés a Pedro |
| "El kiosco le pagó 300 mil a Martín de lo que me debe" | Lo mismo |

Pasa seguido: le comprás un lote de dólares a Pedro y le quedás debiendo; Juan, que te
debe, le transfiere directo a Pedro. **Bajan las dos deudas de una y por tu caja no pasa
un peso** — porque esa plata nunca pasó por tu caja: fue de Juan a Pedro.

⚠️ **Ojo con cómo lo decís, que son tres cosas distintas:**

- *"Juan me pagó 500 lucas"* → te trajo la plata a **vos**: **entra** a la caja.
- *"Le pagué 500 lucas a Pedro"* → se la pagaste **vos**: **sale** de la caja.
- *"Juan le transfirió 500 lucas a Pedro"* → **no se mueve la caja**: bajan las dos deudas.

Entre la primera y la tercera hay un simple *"a Pedro"*, y el error es caro: el bot
anotaría plata que nunca entró **y encima** te dejaría viva la deuda con Pedro. Por eso,
cuando compensa, te contesta siempre **"no movió la caja"**. Si ves esa línea y en realidad
te trajeron la plata a vos, avisale.

**Decile los dos nombres y el monto**: quién transfirió, a quién, y cuánto. Si le debés a
varios que se llaman parecido, te pregunta a cuál.

**También lo podés hacer a mano** —cobrarle a Juan por un lado y pagarle a Pedro por el
otro— y funciona igual. Pero ahí quedan anotados un ingreso y un egreso que no existieron,
y si te olvidás de hacer la segunda mitad, la caja te queda con plata de más que no está
en el cajón. En un solo mensaje no te podés olvidar.

### Plata que sale

| Decís | Hace |
|---|---|
| "Cargué 10 mil de nafta" | Registra el gasto |
| "Gasté milqui en YPF y 12 mil en el kiosco" | Registra los dos gastos |
| "Le debo $50.000 a Fernando por los insumos" | Anota la deuda **del negocio** |
| "Kiosco me debe 200 lucas de la mercadería" | Anota la deuda **del cliente** y descuenta la plata de la caja |

En las deudas **siempre decí el motivo**. Si no, te lo pregunta.

**Ojo con cómo lo decís, porque son cosas opuestas:**

- *"Le debo a Fernando"* → lo que **vos le debés** a alguien. No mueve la caja.
- *"Fernando me debe"* → lo que **te deben a vos**. Descuenta la plata de la caja del día,
  porque esa plata salió.
- *"Le presté a Fernando en 6 cuotas"* → arma un **préstamo con cuotas**.

Si le diste plata sin pactar cuotas, decilo como *"me debe"*. El bot te contesta cuánto
salió de caja: si ahí ves un descuento que no esperabas, avisale en el momento.

### Préstamos y dólares

| Decís | Hace |
|---|---|
| "Presté $500.000 a María en 6 cuotas mensuales, total $750.000" | Arma el préstamo |
| "Compré 1.000 dólares a 1.250" | Registra la compra |
| "Vendí 500 USD a 1.310" | Registra la venta y calcula la ganancia |
| "Compré 1.000 dólares a 1.250 a Pedro pero no se los pagué" | Los dólares entran igual y quedan **debiéndose** a Pedro |
| "Le compré el cheque 4455 al 10% a Juan y le pago la semana que viene" | El cheque entra a cartera y queda **debiéndose** a Juan |
| "Le di 200 mil de los 900 del cheque" | Sale de caja solo lo que pagaste; el resto queda debiéndose |

**La cotización la decís vos, siempre.** El bot nunca la inventa.

**Cuando comprás sin pagar.** Decilo con todas las letras: *"no se los pagué"*,
*"le pago después"*, *"quedé debiendo"*. La mercadería entra igual —los dólares a tu
stock, el cheque a tu cartera— pero **de la caja no sale la plata que no pagaste**: queda
anotada como deuda tuya con el vendedor, y la vas a ver en la sección Deudas del panel.

Dos cosas para tener en cuenta:

- **Decí a quién se lo comprás.** Sin nombre no puede anotar la deuda, así que te pregunta.
- **De un cheque se debe lo que vale, no lo que dice.** Un cheque de $1.000.000 al 10% se
  compra por $900.000: eso es lo que le quedás debiendo.

Si no aclarás nada, el bot asume que **la pagaste** — que es lo normal. Por eso siempre te
contesta **cuánto salió de caja**: si ahí ves el total cuando en realidad no pagaste,
avisale en el momento.

### Preguntas

- "¿Qué cheques tengo?"
- "¿Qué me debe Juan?"
- "¿Qué préstamos tengo por cobrar?"

---

## Cuando te pregunta "¿confirmo?"

Pasa con montos grandes, cheques rechazados, varios cheques juntos, borrar algo o un gasto
que parece repetido.

**Para que se haga:** *sí · dale · ok · listo · de una · mandale · 👍*
**Para que no se haga:** *no · cancelá · pará · dejá · mejor no · ❌*

Tres cosas:

- Hasta que no contestes, **no se cargó nada**.
- Si contestás cualquier otra cosa, la operación se cancela y hay que empezar de nuevo.
- **Por audio no se confirma.** Escribilo.

Cancelar no rompe nada. Ante la duda, cancelá y cargá de nuevo.

---

## Corregir algo mal cargado

> "El cheque 4581 tiene mal el porcentaje, era 3 no 2"
> "El gasto de nafta era $8.000 no $5.000"
> "La deuda con Fernando son $60.000"

Si hay varios gastos parecidos, decíle cuál: *"el de las 21:17"* o *"el de 5.000"*.

**Los gastos solo se corrigen el mismo día.** Los de días anteriores, por el panel.
**Los dólares no se corrigen por chat** (hay que borrar la operación o cargar una que compense).

## Borrar algo

> "El 4581 no se vendió, volvelo a cartera"    → el cheque vuelve a estar disponible
> "Borrá el gasto de nafta de recién"          → se elimina y se descuenta de la caja
> "El préstamo a Juan no va, eliminalo"

Siempre te pide confirmar y te muestra qué se va a descontar. Leelo antes de decir que sí.

Hay cosas que no te va a dejar borrar: un fiado que ya cobraste en parte, dólares que ya
vendiste, o un cheque que usaste para pagar una deuda. Eso se resuelve en el panel.

---

### Deshacer una compensación

Decile *"deshacé la transferencia que Juan le hizo a Pedro"* o *"borrá la última
compensación"*. Las dos deudas vuelven a como estaban y la caja no cambia, porque nunca
se había movido.

## Lo que NO hace el bot

Para esto hay que entrar al panel web:

- Pagar o cancelar las deudas del negocio (las anota, no las paga).
- **Cobrar** las "Otras deudas" de clientes (las anota, no las cobra).
- Cobrar un préstamo por un monto que no sea una cuota entera (ej: paga $30.000 de una
  cuota de $50.000).
- Cargar algo con fecha de otro día.
- Corregir gastos viejos o movimientos de dólares.
- Reportes, cierre de caja y backups.

Y hay dos casos en los que el bot frena y te manda al panel, a propósito: cuando un cliente
tiene **dos fiados abiertos** o **dos préstamos activos** a la vez. No puede adivinar cuál
cobrar, y equivocarse ahí descuadra las dos cuentas.

---

## Cuidado con los nombres

Si el nombre no existe, **el bot crea un cliente nuevo sin preguntar**.

Eso significa que "Gomez" y "Gómez" son dos personas distintas para el sistema, y la deuda
te queda partida al medio.

- Escribí siempre igual el mismo nombre.
- Usá nombre y apellido.
- Si hay dos parecidos, te pregunta cuál. Contestá con el nombre completo.

---

## Si algo no funciona

| Te dice | Hacé |
|---|---|
| "No pude interpretar el mensaje" | Decilo más directo: qué hiciste, cuánto y con quién |
| "No encontré ningún cliente llamado X" | Fijate cómo está escrito en el panel |
| "Hay varios clientes que coinciden" | Contestá con el nombre completo |
| "Hay varios cheques con ese número" | Agregá el banco |
| "Posible gasto duplicado" | Si es real, confirmá. Si no, cancelá |
| "No pude transcribir el audio" | Mandalo escrito |
| "Error interno del sistema" | Avisá al administrador |

**Si no contesta nada:**

1. Fijate que le estés escribiendo al chat del bot (en grupos no funciona).
2. Fijate que no sea un PDF, un video o un sticker: eso no lo lee.
3. Probá con *"¿qué cheques tengo?"*. Si tampoco responde, avisá al administrador.
4. **No repitas la operación diez veces.** Cuando vuelva, se puede cargar todo junto.
   Anotala en papel y cargala después desde el panel.

---

## Cómo funciona la caja

La caja es un cuaderno de **plata que se movió de verdad**. Cada operación que cargás
escribe ahí un renglón, y el reporte del día es la suma de esos renglones. Nada más.

Hay **dos cajas separadas: pesos y dólares.** Un gasto en dólares no baja la caja de pesos.

### Lo que hace ENTRAR plata

| Operación | Entra |
|---|---|
| Vendés un cheque | lo que te pagaron: nominal **menos** el % de venta |
| Cobrás un cheque en ventanilla | el nominal **completo** |
| Te pagan una cuota de préstamo | lo que cobraste |
| Te pagan un fiado en efectivo | lo que cobraste (aunque sea parcial) |
| Vendés dólares | los pesos que recibiste |

### Lo que hace SALIR plata

| Operación | Sale |
|---|---|
| Comprás un cheque | lo que pagaste: nominal **menos** el % de compra |
| Cargás un gasto | el gasto, en su moneda |
| Otorgás un préstamo | la plata que entregaste |
| Comprás dólares | los pesos que pagaste |
| Pagás una deuda del negocio | lo pagado, en la moneda con la que pagaste |

### Lo que NO mueve la caja (aunque lo parezca)

- **Anotar una deuda del negocio.** Todavía no pagaste nada. Mueve la caja recién cuando
  la pagás (y eso se hace desde el panel).
- **Fiar un cheque.** No entró plata: entregaste el papel a crédito. Entra cuando el
  cliente te paga.
- **Recibir un cheque como pago** de un fiado o de una cuota. No entró efectivo, entró un
  papel. Esa plata entra a la caja el día que **vendas o cobres** ese cheque.
- **Los cheques que ya tenías antes de arrancar el sistema.** Esos los pagaste antes, y el
  efectivo con el que se abrió el sistema ya los tiene descontados. Contarlos otra vez
  sería restar la misma plata dos veces.
- **Comprar sin pagar.** Los dólares o el cheque entran, pero la plata sigue en el cajón:
  sale el día que le pagues al vendedor.
- **Que un cliente le transfiera a alguien a quien vos le debés.** Bajan las dos deudas,
  pero esa plata fue de uno al otro sin pasar por tu caja.

### Por qué un buen día puede aparecer "en rojo"

Un ejemplo con un cheque de $100.000:

| | |
|---|---|
| Lo comprás al 8% | **salen $92.000** |
| Lo vendés al 3% | **entran $97.000** |
| Tu ganancia | $5.000 |

Si lo comprás un día y lo vendés al otro, **el primer día la caja da −$92.000** y el
segundo +$97.000. El primer día no perdiste plata: la cambiaste por un cheque.

Por eso el reporte muestra dos números distintos:

- **Neto** = lo que entró menos lo que salió **ese día**. Puede dar negativo, y está bien.
- **Saldo** = la plata que hay en el cajón: lo que había al empezar el día, más lo que
  entró, menos lo que salió.

**El que tiene que coincidir con el efectivo del cajón es el saldo, no el neto.**

Si al cerrar el día no te cierra, mirá primero la lista de movimientos del día en el panel.
Si aun así no cierra, hablalo con el administrador antes de tocar nada.
