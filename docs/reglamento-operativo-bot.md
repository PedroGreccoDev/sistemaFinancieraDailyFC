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
| "Juan pagó" | Cobra la próxima cuota que vence |
| "Pedro pagó la 3" | Cobra esa cuota |
| "María abonó 2 cuotas" | Cobra dos |
| "Juan me pagó $50.000 del fiado" | Cobra el fiado (acepta pagos parciales) |
| "Juan me trajo el cheque 9988 de $100.000 al 2% para el fiado" | Entra el cheque y salda el fiado |

### Plata que sale

| Decís | Hace |
|---|---|
| "Cargué 10 mil de nafta" | Registra el gasto |
| "Gasté milqui en YPF y 12 mil en el kiosco" | Registra los dos gastos |
| "Le debo $50.000 a Fernando por los insumos" | Anota la deuda del negocio |

En las deudas **siempre decí el motivo**. Si no, te lo pregunta.

### Préstamos y dólares

| Decís | Hace |
|---|---|
| "Presté $500.000 a María en 6 cuotas mensuales, total $750.000" | Arma el préstamo |
| "Compré 1.000 dólares a 1.250" | Registra la compra |
| "Vendí 500 USD a 1.310" | Registra la venta y calcula la ganancia |

**La cotización la decís vos, siempre.** El bot nunca la inventa.

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

## Lo que NO hace el bot

Para esto hay que entrar al panel web:

- Pagar o cancelar las deudas del negocio (las anota, no las paga).
- "Otras deudas" de clientes.
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
