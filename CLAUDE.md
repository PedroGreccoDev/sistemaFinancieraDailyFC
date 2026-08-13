# CLAUDE.md — Sistema Financiera Daily FC

Guía de referencia rápida para el asistente de IA. Lee esto antes de tocar cualquier archivo.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Backend API | FastAPI + Python 3.12 |
| Base de datos | PostgreSQL (psycopg3) |
| ORM / migraciones | SQLAlchemy 2.0 + Alembic |
| Frontend | React + Vite + TypeScript |
| IA (razonamiento/OCR) | Claude (Anthropic) |
| IA (transcripción audio) | Whisper (OpenAI) |
| Bot WhatsApp | WAHA (NOWEB) → webhook FastAPI |
| Deploy | Railway (monorepo, `railway.toml`) — alternativa VPS vía `docker-compose.yml` + `infra/` |

---

## El libro de caja (`MovimientoCaja`) — la columna vertebral

Toda entrada y salida de plata del negocio se anota como **un renglón** en una única tabla,
`movimientos_caja` (modelo `MovimientoCaja`, creada en la migración `0013`). Es la **fuente
única** del reporte de caja diaria (§7): el reporte no recalcula nada, solo **suma estos
renglones** por moneda y día.

**Cómo se escribe un renglón.** Los servicios de negocio lo asientan con el helper
`caja.registrar(...)` (`app/services/caja.py`) en el call site de cada operación —no la máquina
de estados del cheque, porque el significado de caja depende del contexto—. `registrar()`
**agrega la fila a la sesión sin hacer commit**: se persiste con el commit del propio servicio,
de modo que el asiento de caja y la operación de negocio son **atómicos** (o ambos o ninguno).

**Qué guarda cada renglón:**
- `fecha` — día local ART del evento (el reporte filtra por día directo, sin conversión de zona).
- `moneda` — `ARS` | `USD` (la caja se lleva separada por moneda).
- `tipo` — `INGRESO` (entra plata) | `EGRESO` (sale plata). El `monto` es **siempre positivo**;
  el signo lo da el `tipo`.
- `categoria` — el origen del movimiento: `COBRO_CUOTA`, `COBRO_FIADO`, `VENTA_CHEQUE`,
  `COBRO_CHEQUE`, `COMPRA_CHEQUE`, `COMPRA_USD`, `VENTA_USD`, `OTORGAMIENTO_PRESTAMO`, `GASTO`,
  `PAGO_PASIVO`, `VUELTO_PASIVO`, `OTORGAMIENTO_DEUDA`, `COBRO_DEUDA`, `AJUSTE_CAJA`.
- `referencia_tipo` / `referencia_id` — enlace flojo a la entidad que lo originó
  (cheque/préstamo/cuota/fiado/pasivo/gasto/movimiento/deuda_simple/deuda_simple_cobro).
  `COBRO_CUOTA` referencia la `cuota`
  cuando se cobra una cuota entera, o el `prestamo` cuando es un pago de **importe libre** (§3).
- `ganancia` — solo en `VENTA_USD`: ganancia FIFO realizada en ARS. Es dato de **reporte**, no de caja.
- `medio_pago` — solo en `PAGO_PASIVO`: `EFECTIVO` | `TRANSFERENCIA` (enum `medio_pago`, migración `0014`); null en el resto.
- `cotizacion` — `$/USD` aplicado cuando un pago cruza monedas (deuda y pago en monedas distintas);
  la usan `PAGO_PASIVO` (§5), `COBRO_FIADO` (§2) y `COBRO_CUOTA` (§3). Null si comparten moneda. Dato de reporte/auditoría.
- `detalle` — texto libre con el detalle de la línea.

**"Resincronizar la caja" = rehacer esos renglones.** Cuando un módulo edita una operación ya
asentada, **borra los renglones de esa entidad** (`caja.borrar_por_referencia(referencia_tipo,
referencia_id)`) y los vuelve a registrar con los valores corregidos. Eso es exactamente lo que
hacen los `resync_caja_*` / `_resync_caja_*` que aparecen en cada módulo: mantener el cuaderno
en sync con la operación de negocio.

---

## Apertura del sistema — los saldos con los que arrancó _(régimen definido 2026-08-06)_

Cuando el sistema se puso en marcha el negocio **ya venía funcionando**: había efectivo
en el cajón y cheques en cartera comprados tiempo atrás. Los dos son **saldos de
apertura**, no operaciones del día. Tabla singleton `configuracion_apertura` (modelo
`ConfiguracionApertura`, migración `0018`), servicio `svc_apertura`, router `/apertura`.

- **Fecha de corte (`fecha_corte_carga_inicial`).** Hasta esa fecha **inclusive**, un
  cheque que se carga es cartera preexistente: se marca `es_carga_inicial` y **NO asienta
  el egreso `COMPRA_CHEQUE`**. Esa plata salió antes de que el sistema existiera y el
  efectivo de apertura **ya la tiene descontada**: asentarla la restaría **dos veces**.
  Es automático (lo resuelve `create_cheque` vía `svc_apertura.es_carga_inicial`), no
  depende de que el operador tilde nada — el olvido es donde se cometen los errores.
- **Se aplica hacia atrás:** `definir_fecha_corte` marca los cheques ya cargados dentro
  del período y les **borra el egreso de compra** que no correspondía. Solo el egreso: si
  el cheque ya se vendió o cobró, ese ingreso es plata real y se conserva.
- **`resync_caja_cheque` respeta la marca** (en `svc_cheques` y en el `dispatcher`): sin
  eso, editar un cheque de carga inicial le haría aparecer un egreso que nunca existió.
- **Saldo inicial:** efectivo en mano al arrancar, por moneda, con **la fecha a la que
  corresponde** —no la fecha en que se tipea—, así se puede cargar días después y los
  reportes viejos igual cierran. Asienta una línea `SALDO_INICIAL` por moneda. Es **por
  única vez**: rehacerlo exige `forzar=true`.
- **`SALDO_INICIAL` no es un ingreso del día.** El reporte lo excluye de
  `ingresos_total`/`neto` y lo suma al **saldo de apertura**; su grupo es `APERTURA`. Si
  contara como ingreso, el día en que se carga aparecería con una entrada gigante que
  nunca ocurrió.
- **El saldo inicial es un PUNTO DE CORTE, no un sumando.** Con un saldo inicial en la
  fecha `F`, el saldo de apertura de un día `D ≥ F` suma solo los movimientos en `[F, D)`:
  la línea `SALDO_INICIAL` entra sola por tener fecha `F` y **todo lo anterior queda
  afuera a propósito**. El efectivo que el dueño contó ese día ya tiene descontado lo que
  pasó antes; sumarlo lo restaría dos veces. Esto es lo que hace que **no haga falta
  revertir los otorgamientos de préstamos, fiados y deudas preexistentes**: a diferencia
  de los cheques —que se siguen operando y por eso sí hay que corregirlos—, esos egresos
  viejos simplemente quedan del otro lado de la línea.
- **El reporte cierra como una caja de verdad:** `saldo_apertura` `+ ingresos − egresos =
  saldo_cierre`. El `neto` sigue siendo el **flujo** del período: un día de solo compras da
  negativo —correcto, salió plata— sin que el **saldo** esté en rojo.
- **Dólares de apertura: el efectivo NO alcanza, hace falta el lote.** El `saldo_inicial_usd`
  da el **efectivo** en la caja USD, pero la venta consume **lotes** `MovimientoEfectivo` de
  tipo `COMPRA` con `usd_restante > 0` (§4): sin lote no se pueden vender aunque el saldo
  diga que están. Por eso `definir_saldo_inicial` **exige `cotizacion_usd`** cuando
  `saldo_usd > 0` y crea un lote con `es_apertura=True` (migración `0019`) a ese costo
  promedio — mejor frenar en la carga que descubrirlo al intentar vender.
  - Ese lote se inserta con `db.add()` y **no asienta caja**: los pesos salieron antes de que
    el sistema existiera, y la caja USD ya la aporta la línea `SALDO_INICIAL`. Asentarlo
    duplicaría los dólares. `_resync_caja_movimiento` corta temprano si `es_apertura`, para
    que editarlo tampoco le invente líneas.
  - `_rehacer_lote_usd` **borra el lote anterior** antes de crear el nuevo: la apertura es
    una sola, y corregir el saldo o la cotización no debe acumular lotes.
  - El promedio es una aproximación de apertura: la ganancia de las primeras ventas se
    calcula contra él. Cada compra posterior guarda su costo real y el FIFO vuelve a ser exacto.

---

## Ajustes de caja — agregar o restar efectivo a mano _(régimen definido 2026-08-10)_

Toda otra línea del libro nace de una operación de negocio. Un **ajuste** es la
excepción explícita: plata que entra o sale **sin** operación detrás. Tabla
`ajustes_caja` (modelo `AjusteCaja`, migración `0020`), servicio `svc_ajustes_caja`,
router `/ajustes-caja`, categoría `AJUSTE_CAJA`, grupo de reporte `AJUSTES`.

- **Motivos** (`AjusteCajaMotivo`): `CORRECCION` (el sistema no coincide con el
  efectivo real del cajón), `APORTE` / `RETIRO` (el dueño puso o sacó plata) y
  `OTRO`, que **exige descripción** — sin la razón escrita, en un mes nadie puede
  reconstruir por qué la caja se movió sola.
- **Cuenta como ingreso/egreso del período** (decisión del dueño). A diferencia de
  `SALDO_INICIAL`, **no** va al saldo de apertura: un aporte levanta el neto del día
  como si hubiera sido un buen día de operación. Es a propósito — el neto es el flujo
  real de caja. Si algún día molesta al leer el reporte, moverlo a una línea aparte
  es cambiar su grupo en `_GRUPO_POR_CATEGORIA`.
- **Es una entidad propia, no una línea suelta del libro**, para poder auditar el
  motivo y anularla con el motor común (`/anulaciones/ajuste_caja/{id}`).
- **No se edita: se anula y se vuelve a cargar.** Un ajuste en USD mueve la cadena
  FIFO y editarlo obligaría a reescribir imputaciones ya hechas. Anular deja además
  el rastro de qué se corrigió y por qué.

**Dólares — el efectivo no alcanza, hace falta el stock.** La caja USD y el stock
vendible son cosas distintas (§4). Por eso:

- **Sumar USD exige `cotizacion_usd`** y crea un lote `MovimientoEfectivo` con
  `es_ajuste=True`, igual que el lote de apertura. Ese lote **no asienta caja** (la
  caja USD ya la mueve la línea `AJUSTE_CAJA`): `_resync_caja_movimiento` corta
  temprano con `es_apertura or es_ajuste`, y `list_movimientos` lo excluye para que
  no figure como una compra que nunca ocurrió.
- **Restar USD consume lotes FIFO sin realizar ganancia** —esos dólares se fueron,
  pero nadie los compró—. Falla con `ValidationError` si no hay stock.
- **Los ajustes tienen que entrar en `_reimputar_fifo`.** Esa función resetea el
  stock de **todos** los lotes y lo vuelve a imputar; un consumo hecho por fuera se
  restauraría **solo y en silencio** la próxima vez que alguien editara o anulara una
  operación de divisas. `_consumidores_de_stock` mezcla ventas y ajustes en orden
  cronológico; el ajuste se ubica al **arranque de su día** (solo guarda la fecha,
  no la hora) para no reordenar las ventas entre sí, que se comparan por
  `fecha_operacion` completa.
- **Bloqueos al anular** (`_validar_ajuste`): un ajuste que sumó USD cuyo lote ya fue
  vendido (aunque sea en parte), y uno que restó USD con ventas posteriores. Mismo
  criterio que las operaciones de divisas: hacia atrás solo se deshace la última.
  En ARS nunca hay bloqueo. Anular un ajuste que sumó dólares **borra su lote**
  (el lote no tiene historia propia; el ajuste sí queda anulado y auditable).
- **Backup:** `es_apertura` y `es_ajuste` viajan en el export (`_MO`) — ver §8 para por
  qué las listas de columnas tienen que estar completas. `ajustes_caja` se borra
  **primero** y se inserta **después** de `movimientos_efectivo`: apunta a su lote por FK.

**Panel:** botón "± Ajustar caja" en la página **Movimientos**
(`ModalAjusteCaja`), y botón "Eliminar" en las filas del grupo `AJUSTES` del feed.
No hay intent de bot.

---

## Anulación y reversión — "Eliminar" no borra _(régimen definido 2026-08-06)_

El botón **Eliminar** del panel **anula**: la fila queda con `anulado_at` /
`anulado_por` / `motivo_anulacion` (mixin `AnulableMixin`, migración `0017`), sale de
los listados y **sus líneas del libro de caja se revierten**. Se conserva la historia
para poder auditar después por qué la caja dio distinto; un `DELETE` físico haría
imposible esa reconstrucción.

- **Ortogonal al estado.** Un cheque anulado conserva su `estado` histórico. **No** hay
  valor `ANULADO` en los enums: rompería la máquina de estados y los reportes.
- **Motor único:** `app/services/anulacion.py`, base común del botón del panel, la
  reversión y (pendiente) el bot. `anular()` barre **todas** las `refs` de caja de la
  entidad —un préstamo asienta con `prestamo` y `cuota`; una deuda simple con
  `deuda_simple` y `deuda_simple_cobro`—; el catálogo `_ENTIDADES` fija ese mapa y hay
  tests que lo custodian. **Una entidad anulable nueva se da de alta ahí y en el test
  que custodia el catálogo**, o la anulación la marcaría de baja dejando sus líneas de
  caja vivas.
- **Reversión ≠ anulación.** `revertir_cheque` devuelve un cheque terminal a
  `EN_CARTERA` **sin eliminarlo** (queda disponible para volver a venderse): borra el
  ingreso de venta/cobro y **conserva el egreso de la compra**, que sigue siendo cierto.
  Es la única puerta que abre los estados terminales, y solo hacia atrás.
- **Previsualización obligatoria:** `GET /anulaciones/{entidad}/{id}` devuelve el
  impacto (líneas de caja a revertir, qué arrastra, bloqueo si lo hay) para que el panel
  lo muestre **antes** de confirmar. `POST` en la misma ruta ejecuta. Toda anulación
  exige `operador_id` + `motivo`.
- **Bloqueos** (lo que no se puede deshacer solo): un fiado que ya recibió cobros
  parciales; una **compra** de USD cuyo lote ya fue consumido; una **venta** de USD que
  no es la última (reescribiría ganancias FIFO ya reportadas); un cheque entregado para
  pagar un pasivo; un **ajuste de caja** en USD que trabó la cadena (§Ajustes de caja).
- **Cascadas:** anular un cheque `FIADO` arrastra su fiado; anular un **fiado** devuelve
  el cheque a `EN_CARTERA` (si no, quedaría entregado a crédito sin nadie debiendo).
- **Unicidad sobre las filas vivas:** `(banco, nro_cheque)` y "un fiado por cheque" son
  **índices únicos PARCIALES** con `WHERE anulado_at IS NULL`. El caso normal es cargar
  mal un cheque, anularlo y recargarlo con el mismo número.
- **Al anular divisas hay que `db.flush()` antes de `_reimputar_fifo`:** la sesión va con
  `autoflush=False` y si no, el SELECT no ve la marca recién puesta y la operación
  anulada sigue aportando o consumiendo stock USD.
- **Todo listado nuevo debe filtrar `anulado_at IS NULL`.** Ya lo hacen los `list_*`, el
  feed de Movimientos, el snapshot de pasivos, el historial de cuotas cobradas, el FIFO y
  las búsquedas del bot.
- **Backup:** el **JSON** conserva los anulados con su marca (copia fiel de la base; si no
  los llevara, un ciclo export→import los resucitaría). El **Excel** los excluye: es un
  reporte de trabajo y una operación dada de baja no debe figurar como real.

---

## Módulos de negocio

### 1. Chequera Virtual

- **Identidad:** la PK de `cheques` es la subrogada `id` (UUID). El `nro_cheque` **no es
  único globalmente** (solo lo es dentro de un banco); por eso la unicidad real es
  `(banco, nro_cheque)`. El operador/OCR registra el `banco`; si no se detecta queda
  `NULL` y la unicidad no bloquea (en Postgres NULL ≠ NULL). Las referencias del bot por
  número se resuelven con `svc_cheques.resolve_cheque`, que pide desambiguar por banco si
  hay varios candidatos. La API identifica cheques por `id`, no por número.
- Un cheque nuevo **siempre** entra en estado `EN_CARTERA`.
- La máquina de estados es **estricta**: `EN_CARTERA` → `VENDIDO | FIADO | COBRADO | RECHAZADO`.
- Los estados `VENDIDO`, `FIADO`, `COBRADO` y `RECHAZADO` son **terminales**: no admiten más cambios.
- `COBRADO` y `RECHAZADO` son eventos exclusivamente manuales del operador.
- `FIADO` **solo** se procesa con la transacción atómica `fiar_cheque` (crea cheque FIADO + registro `Fiado` en el mismo commit). **No genera préstamo ni cuotas.**
- Toda transición manual requiere `operador_id` y `motivo` no vacíos.
- **Foto del cheque:** los cheques cargados por WhatsApp guardan la imagen (migración `0009`); se visualiza en el panel con `ChequeFotoModal`.
  - El endpoint `GET /cheques/{id}/foto` se monta en un **router público** (`cheques.public_router`, sin `get_current_user`): se sirve por **UUID no-adivinable** para que funcione en `<img src>` directos del panel (p. ej. la miniatura de `Cartera`), que no pueden enviar el header `Authorization`. **La protección es la entropía del UUID, no la sesión** — si esos UUIDs se filtran (logs, links), la foto queda expuesta. El resto de `cheques.router` sigue protegido. Si se necesita cerrar el acceso sin romper los `<img>`, el camino es un token firmado en la query (`?token=`).
- **Editar carga (panel + bot):** `PATCH /cheques/{id}` (`svc_cheques.editar_cheque`) corrige la carga y resincroniza la caja (`resync_caja_cheque`). Reglas: `COBRADO`/`RECHAZADO` son terminales y NO editables; `EN_CARTERA` edita campos base; `VENDIDO`/`FIADO` además `porcentaje_venta` (recalcula ganancia, y el saldo del fiado solo si aún no recibió cobros parciales). En el panel está el botón "Editar" por fila en Cartera (en cartera y en el historial de ventas); el modal permite además reasignar cliente origen/destino (con alta de cliente inline).
- **Eliminar y Revertir (panel):** botones por fila en Cartera. Eliminar **anula** (no borra) y revierte la caja; Revertir devuelve un cheque terminal a `EN_CARTERA` dejándolo disponible para volver a operarse. Ver §Anulación y reversión.
- **Cartera preexistente (`es_carga_inicial`):** un cheque cargado dentro del período de apertura **no asienta el egreso de compra** —ya estaba comprado antes de que el sistema existiera—. Ver §Apertura del sistema.

### 2. Fiados _(módulo agregado 2026-06-09)_

Cuando se **fía** un cheque se genera una **deuda abierta** del cliente, sin cuotas fijas.

**Saldo inicial:** `monto_cheque × (1 − porcentaje_venta / 100)`
(el porcentaje_venta es el descuento pactado al entregar el cheque).

El cliente puede cancelar esa deuda de dos formas:

**a) En efectivo:**
- Se registra con `POST /fiados/{id}/cobrar-efectivo` (`monto_cobrado`).
- El monto debe ser ≤ `saldo_pendiente`. Se puede pagar en partes.
- Cuando `saldo_pendiente` llega a 0, el fiado pasa a `CANCELADO`.
- **Pago en moneda distinta (cross-currency):** la deuda del fiado es **siempre ARS**, pero
  el cobro puede venir en USD. El payload acepta `moneda_pago` (default `ARS`) y `cotizacion`
  ($/USD, obligatoria si `moneda_pago` ≠ ARS). El saldo (ARS) baja por el equivalente
  (`monto × cotizacion`) vía la función pura `conversion.calcular_reduccion_saldo`; **la caja
  recibe la plata en la moneda efectivamente cobrada** (INGRESO `COBRO_FIADO` en esa moneda,
  con la `cotizacion` guardada para auditoría).

**b) Con otro cheque:**
- Se registra con `POST /fiados/{id}/cobrar-con-cheque`.
- `valor_neto_cheque = monto_cheque × (1 − porcentaje_compra / 100)`
- `diferencia = valor_neto_cheque − saldo_pendiente`
  - `diferencia ≥ 0` → fiado `CANCELADO`; si `diferencia > 0` el negocio **le debe** al cliente esa diferencia.
  - `diferencia < 0` → `saldo_pendiente = −diferencia`; el cliente aún debe el resto (puede saldar en efectivo).
- El cheque recibido **siempre** entra al sistema como `EN_CARTERA` con `cliente_origen_id = cliente del fiado`.

**Estados:** `ABIERTO` → `CANCELADO` (único estado terminal).
**Restricción:** un cheque solo puede originar un fiado (`UNIQUE` en `cheque_nro`).
**Bot WhatsApp:** intents `FIAR_CHEQUE`, `COBRAR_FIADO_EFECTIVO`, `COBRAR_FIADO_CON_CHEQUE`.

---

### 2.b Deudas simples _(deuda libre de cliente — módulo agregado 2026-07-18)_

Cuenta por cobrar de un cliente que **no** es un préstamo con cuotas ni un fiado de
cheque: una **deuda libre** con su **razón** (`concepto`), monto, moneda (`ARS`|`USD`)
y fecha. Conceptualmente "un fiado sin cheque y con divisa". Tabla `deudas_simples`
(modelo `DeudaSimple`, migración `0016`), servicio `svc_deudas_simples`, router
`/deudas-simples`.

- **Ciclo de caja completo (régimen definido 2026-07-18):** al **registrarla** sale un
  **EGRESO** `OTORGAMIENTO_DEUDA` en su moneda y fecha (se entregó la plata, sin cuotas);
  al **cobrarla** entra un **INGRESO** `COBRO_DEUDA` en la moneda efectivamente cobrada.
- **Cobros parciales y totales:** lleva `saldo_pendiente`; se cobra en partes con
  `POST /deudas-simples/{id}/cobrar` (`monto_cobrado`). Cuando el saldo llega a 0 pasa a
  `CANCELADA` (con `fecha_cancelacion`). Soporta **cross-currency** vía la función pura
  compartida `conversion.calcular_reduccion_saldo`: la cotización imputa cuánto baja el
  saldo (en la moneda de la deuda), pero la caja recibe la plata en la moneda pagada. La
  primera cotización cross-moneda se guarda en `cotizacion_pago` como default editable.
- **Estados:** `ABIERTA` → `CANCELADA` (transición única, irreversible).
- **Dos `referencia_tipo` de caja:** el egreso de origen usa `deuda_simple` y cada cobro
  usa `deuda_simple_cobro`, para que la edición resincronice **solo** el egreso de origen
  (`_registrar_egreso_origen`) sin tocar las líneas de los cobros ya hechos.
- **Cobro con cheque** (`POST /deudas-simples/{id}/cobrar-con-cheque`,
  `svc_deudas_simples.cobrar_con_cheque`): el cliente paga con un cheque en vez de efectivo.
  El cheque entra `EN_CARTERA` con `cliente_origen_id` = cliente de la deuda y salda por su
  **valor neto** (`monto × (1 − %compra)`), no por el nominal. **No asienta caja**: no entró
  efectivo — la plata se reconoce al vender o cobrar ese cheque (mismo criterio que §2 y §3),
  y por eso se inserta con `db.add()` y no con `create_cheque()`.
  - **Un cheque "de más" es el caso normal, no un error.** El cliente entrega el cheque que
    tiene. Si vale más que el saldo, la deuda se cancela y la `diferencia` (> 0) queda a favor
    del cliente. Por eso usa `conversion.convertir_a_moneda_deuda` (convierte sin topear) y
    **no** `calcular_reduccion_saldo`, que rechaza un pago mayor al saldo — correcto para
    efectivo, roto para cheques.
  - Cross-currency: los cheques son siempre ARS, así que una deuda en USD exige `cotizacion`.
- **Editar carga:** `PATCH /deudas-simples/{id}` (`svc_deudas_simples.editar_deuda_simple`).
  `concepto`/`fecha`/`observaciones` siempre; `monto`/`moneda` solo si está `ABIERTA` y sin
  cobros parciales (`saldo == monto`); al editar se resincroniza el egreso de origen.
- **Solo panel web** (no hay intent de bot). En el panel vive en la pestaña **"Otras
  deudas"** de Deudores y en el consolidado **General** (botón "Nuevo"); se cobra con el
  modal compartido `ModalPagarDeuda` (tipo `deuda_simple`) y el alta con
  `ModalNuevaDeudaSimple`. Incluida en el backup JSON export/import.

---

### 3. Préstamos y Cuotas _(sin cheque asociado)_

- Monedas soportadas: `ARS` y `USD`.
- Frecuencias: `diaria | semanal | quincenal | mensual | anual`.
- La ganancia teórica del préstamo es `total_a_cobrar - credito` (se guarda como referencia).
- El préstamo pasa a estado `CANCELADO` automáticamente cuando se cobra la última cuota.
- El monto de cada cuota se divide uniformemente; el centavo sobrante cae en la **última** cuota.
- **Reconocimiento en caja (régimen caja diaria, definido 2026-06-25 — ✅ implementado):** el
  ingreso se cuenta **al cobrar cada cuota, NO al originar el préstamo**. Cada cuota cobrada
  asienta un INGRESO `COBRO_CUOTA` en la `fecha_cobro`, con detalle de cliente/préstamo/cuota
  (`svc_prestamos._registrar_cobro_cuota`, usado por cobro simple y en lote). El otorgamiento
  del crédito asienta un EGRESO `OTORGAMIENTO_PRESTAMO` el día en que se da (`create_prestamo`).
  El cobro **con cheque** no asienta efectivo: el cheque entra a cartera y la plata recién se
  reconoce al venderlo/cobrarlo. (Migrado en el commit `feat(caja): reporte de caja diaria…`.)

**Editar carga del préstamo:** `PATCH /prestamos/{id}` (`svc_prestamos.editar_prestamo`) **solo si el préstamo está ACTIVO y ninguna cuota fue cobrada**; cambiar capital/total/cantidad/frecuencia/fecha **regenera el cuadro de cuotas** y rehace el egreso de caja del otorgamiento. En el panel, botón "Editar" en la tarjeta (solo cuando no hay cuotas cobradas).

**Cobro de cuotas desde el panel web** (además del bot, intent `COBRAR_CUOTA`):
- Cobro simple (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobros`.
- Cobro simple en lote (multi-selección): `POST /prestamos/{id}/cuotas/cobrar-lote`.
- Cobro con cheque (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobrar-con-cheque` — genera un cheque `EN_CARTERA`.
- Cobro con cheque en lote: `POST /prestamos/{id}/cuotas/cobrar-con-cheque-lote`.
- **Método de pago "Efectivo" vs "Transferencia" es solo una etiqueta de UI**: el backend NO persiste el medio; solo distingue cobro simple (sin cheque) vs cobro con cheque.

**Pago de importe libre (parcial o total) — régimen definido 2026-07-14 (✅ implementado):** además del
cobro por cuota entera, existe `POST /prestamos/{id}/pagar` (`svc_prestamos.pagar_prestamo`) que
imputa **cualquier importe** contra el préstamo. Para soportarlo, cada `Cuota` lleva `monto_pagado`
(migración `0015`): el saldo de una cuota es `monto − monto_pagado` y la cuota queda `COBRADA` solo
cuando `monto_pagado == monto`. El pago **se imputa a las cuotas más viejas primero** (helper puro
`repartir_pago_en_cuotas`), llenando cada una; al saldarse la última, el préstamo pasa a `CANCELADO`.
Soporta **cross-currency** (mismo `conversion.calcular_reduccion_saldo`): la cotización define cuánto
del préstamo —en su moneda— se salda, pero **la caja recibe una sola línea INGRESO `COBRO_CUOTA` por
el efectivo real, en la moneda pagada** (ref. `prestamo`). Los cobros por cuota entera existentes
asientan solo el **restante** de la cuota (por si traía un pago parcial previo), y todos los flujos
que marcan `COBRADA` fijan `monto_pagado = monto`.

### 4. Movimientos de Efectivo (compra/venta de divisas)

- Operaciones de compra/venta de divisas (ARS ↔ USD).
- **Regla crítica:** la cotización **siempre** la dicta el operador. El sistema jamás la asume ni la consulta.
  `cotizacion_aplicada` = **pesos por 1 USD**; `monto` = **cantidad de USD** de la operación.
  - **COMPRA:** el operador marca a cuánto pagó cada USD. Pesos que salen = `monto × cotizacion`. Es un **egreso** ARS y suma USD al stock.
  - **VENTA:** el operador marca a cuánto le pagaron cada USD. Pesos que entran = `monto × cotizacion`. Es un **ingreso** ARS y descuenta USD del stock.
- **Ganancia por lotes FIFO — sin promedios (régimen definido 2026-06-25):** cada compra
  se guarda como un **lote** con su costo real ($/USD). Cada venta consume lotes en orden
  **FIFO** (los más viejos primero) y la ganancia es exacta:
  `ganancia = Σ (precio_venta − costo_lote) × cantidad_consumida_del_lote` (en ARS).
  Diferencia por dólar positiva → ganancia; negativa → pérdida. **PROHIBIDO promediar costos.**
  La ganancia se realiza en la **venta**; la compra solo incorpora stock a su costo.
  **✅ Implementado:** `svc_movimientos.calcular_ganancia_fifo` (cálculo puro) + `create_movimiento`
  (la compra crea el lote con `usd_restante`; la venta lo consume FIFO y asienta la `ganancia`).
  Cubierto por `tests/test_caja_divisas.py`.
- El widget de Dólar Blue en el frontend es **solo decorativo** (consume DolarAPI externamente).
- **Editar carga:** `PATCH /movimientos-efectivo/{id}` (`svc_movimientos.editar_movimiento`). `cliente`/`observaciones` siempre; `monto`/`cotizacion_aplicada` solo si la operación no está trabada en la cadena FIFO: una **COMPRA** únicamente si su lote está intacto (`usd_restante == monto`), una **VENTA** únicamente si es la última. Al editar se reimputa toda la cadena (`_reimputar_fifo`) y se resincronizan sus líneas de caja. En el panel, botón "Editar" solo en las filas de Divisas de la página Movimientos (las divisas no tienen página propia).

### 5. Pasivos _(módulo agregado 2026-06-08)_

- Registro de **deudas del negocio** con clientes y proveedores (cuentas a pagar).
- **Alta** via bot de WhatsApp (intent `REGISTRAR_DEUDA`) o desde el panel web (botón "Nueva deuda").
- El bot **exige** que el operador indique el concepto; si falta, responde con `ACLARACION_REQUERIDA`.
- **Cancelación** solo desde el panel web (el bot no puede cancelar pasivos).
- Estados: `PENDIENTE` → `CANCELADA` (transición única, irreversible).
- **Pagos parciales:** el pasivo tiene `saldo_pendiente` (migración `0007`); se puede cancelar en partes, en efectivo/transferencia o con un cheque de cartera. Pasa a `CANCELADA` cuando el saldo llega a 0.
- **Pago en efectivo o transferencia (`POST /pasivos/{id}/pagar`, `svc_pasivos.pagar_pasivo`, régimen definido 2026-06-25):**
  - El operador ingresa **el monto que paga, en la moneda con la que paga** (`moneda_pago`) y el **medio** (`EFECTIVO` | `TRANSFERENCIA`, enum `medio_pago`). **La caja se descuenta en esa moneda de pago** (un EGRESO `PAGO_PASIVO` con su `medio_pago`), no en la de la deuda.
  - **La moneda de pago puede diferir de la de la deuda.** Si difiere, el operador ingresa la **cotización (pesos por 1 USD)**, que se usa **solo** para imputar cuánto baja el `saldo_pendiente` (que se lleva en la moneda de la deuda): deuda USD pagada en ARS → `saldo -= monto/cotizacion`; deuda ARS pagada en USD → `saldo -= monto*cotizacion`. La conversión vive en la función pura `calcular_reduccion_saldo` (testeable sin BD), en `app/services/conversion.py` — **compartida** por pasivos, fiados y préstamos (se re-exporta desde `svc_pasivos` por compatibilidad).
  - **La cotización es por pago:** cada cancelación parcial puede usar una distinta. La **primera** se guarda en `pasivos.cotizacion_pago` y el panel la propone como default editable. Cada línea de caja guarda su `cotizacion` aplicada (para reporte/auditoría).
  - Tolerancia de redondeo: un exceso de hasta un centavo sobre el saldo (por convertir de moneda) se trata como cancelación exacta; más que eso es error.
- **Pago con cheque "de más" (régimen definido 2026-06-25):** cuando el valor neto del cheque
  supera el saldo del pasivo, el operador elige qué hacer con el vuelto:
  **(a)** paga la diferencia al cliente en efectivo/transferencia y queda saldada, o
  **(b)** el negocio queda debiendo → se crea **automáticamente un pasivo a favor del cliente**
  por el monto del vuelto. **✅ Implementado:** `svc_pasivos.cancelar_con_cheque` exige `vuelto_modo`
  cuando hay diferencia; `_aplicar_vuelto` resuelve `SALDAR_EFECTIVO` (egreso `VUELTO_PASIVO` en ARS)
  o `QUEDA_DEBIENDO` (crea el pasivo a favor, sin movimiento de caja).
- Campos: `acreedor`, `concepto`, `monto`, `moneda`, `fecha_vencimiento` (opcional).
- **Editar carga:** `PATCH /pasivos/{id}` (`svc_pasivos.editar_pasivo`). `acreedor`/`concepto`/`fecha_vencimiento`/`observaciones` siempre; `monto`/`moneda` solo si está `PENDIENTE` y sin pagos parciales (`saldo == monto`), y al cambiar el monto se recalcula el saldo. El alta no genera línea de caja, así que no hay nada que resincronizar. En el panel, botón "Editar" por fila en Deudas.
- El cierre de caja incluye un snapshot de pasivos pendientes por moneda, **sin filtro de periodo**.
- No existe facturación ni concepto fiscal asociado.

### 6. Gastos Operativos _(módulo agregado 2026-06-08)_

- Registro de gastos de caja del negocio (nafta, insumos, comida, parking, etc.).
- **Carga via bot de WhatsApp** (intent `REGISTRAR_GASTO`) o manual vía API.
- Campos: `concepto`, `monto`, `moneda` (default ARS), `fecha_operacion`, `observaciones`.
- Se descuentan como **egreso** en el reporte para obtener el **neto del período**.
- **Editar carga:** `PATCH /gastos-operativos/{id}` (`svc_gastos.editar_gasto`) corrige concepto/monto/moneda/fecha/observaciones y resincroniza su egreso de caja (`_resync_caja_gasto`). Sin reglas de bloqueo (un gasto es un egreso simple). En el panel, botón "Editar" por fila en la página Gastos.
- **Por moneda (régimen definido 2026-06-25):** un gasto en USD resta del **neto USD** y un gasto
  en ARS resta del **neto ARS**. La caja se lleva separada por moneda. **✅ Implementado:**
  `svc_gastos.create_gasto` asienta el egreso `GASTO` con `moneda=gasto.moneda`; `_resync_caja_gasto`
  lo rehace en la moneda correcta al editar.

### 7. Reportes y Cierre de Caja

**Modelo objetivo (caja diaria, definido 2026-06-25):** el reporte es una **caja de flujo real
de ingresos y egresos efectivos, separada por moneda (ARS y USD)** — NO un P&L devengado. Para
cada moneda: `neto = Σ ingresos − Σ egresos` del período. Cada línea va detallada (origen,
cliente, operación, fecha).

- **Ingresos (entra plata):** cuotas de préstamo cobradas (al cobrar, incluidos cobros parciales),
  cobros de fiado en efectivo (incluidos parciales), cobros de deudas simples (§2.b, incluidos
  parciales), ventas de cheques, ventas de USD (pesos recibidos) y su ganancia FIFO.
- **Egresos (sale plata):** gastos diarios, compra de cheques, compra de USD (pesos que salen),
  compra de cualquier activo, otorgamiento de préstamos (crédito entregado) y otorgamiento de
  deudas simples (§2.b).
- **Cobros parciales cuentan:** si de un fiado de $100.000 entran $100, esos $100 son ingreso
  del día con su detalle (fiado, cliente, fecha).
- **Neto ≠ saldo.** El `neto` es el **flujo** del período; el **saldo** es la plata que hay.
  Cada moneda expone `saldo_apertura` (todo lo anterior al período, vía `_saldo_hasta`, más el
  `SALDO_INICIAL` que caiga dentro) y `saldo_cierre = apertura + ingresos − egresos`. Un día de
  solo compras da **neto negativo —correcto, salió plata—** sin que el saldo esté en rojo. El
  `SALDO_INICIAL` **no** suma a `ingresos_total`: va al saldo de apertura (§Apertura del sistema).
- `GET /api/v1/reportes/cobros-cuotas?desde=&hasta=` devuelve el historial detallado de cuotas
  **COBRADA** (por su `monto` total). Un pago de **importe libre** que deja una cuota a medias
  (§3) todavía no la lista —hasta que se complete—, pero **su efectivo sí figura en el reporte de
  caja** (`/reportes/caja`), que es la fuente de verdad: la línea `COBRO_CUOTA` referencia al `prestamo`.
- **Historial unificado de Movimientos (`GET /api/v1/reportes/movimientos?desde=&hasta=`,
  `svc_reportes.get_movimientos_unificados`):** feed con **TODA operación** del período, venga
  del bot o del panel. Fuente principal: el libro `movimientos_caja` completo (cobros parciales
  y totales, ventas/compras/cobros de cheque, compra/venta USD, otorgamientos, gastos, pagos de
  pasivo y vueltos). Se le suma el **ingreso de cheques a cartera** (tabla `cheques`), un evento
  **sin efectivo** (`flujo=NEUTRO`) que por eso no vive en el libro de caja. Cada ítem trae
  `grupo` (COBROS/CHEQUES/DIVISAS/GASTOS/OTORGAMIENTOS/PASIVOS/APERTURA/AJUSTES), `flujo`
  (INGRESO/EGRESO/NEUTRO) y `referencia_tipo/id`. El front (`pages/Movimientos.tsx`) lo consume
  vía `getMovimientosUnificados` con filtro combinado grupo × flujo; el botón "Editar" sigue solo
  en las filas de divisas (referencia_tipo `movimiento`). **Al agregar una operación nueva que
  asiente en el libro de caja, aparece sola en Movimientos —no hay que tocar esta pantalla.**
  - **Un `grupo` nuevo en el backend hay que darlo de alta en el front.** `MovimientoGrupo`
    (`types/index.ts`) y `GRUPO_CONFIG` son la contraparte del `_GRUPO_POR_CATEGORIA` del
    servidor: un grupo desconocido dejaba `cfg` en `undefined` y el render tiraba la página
    entera a blanco. Ahora `cfgGrupo()` cae en `OTROS`, pero el alta sigue haciendo falta para
    que la fila se vea con su color y entre en el filtro. `SALDO_INICIAL` (grupo `APERTURA`) se
    lista pero **no suma a los chips de ingresos/egresos del día**: es apertura, no plata que
    entró ese día (§Apertura del sistema).

> ✅ **Estado de implementación:** el modelo de caja diaria es el **vigente**. El endpoint es
> `GET /api/v1/reportes/caja?desde=&hasta=` (`svc_reportes.get_reporte_caja`), que lee el libro
> `movimientos_caja` filtrando por `fecha` y arma **una caja por moneda** (ARS y USD) con sus
> líneas detalladas, `ingresos_total`, `egresos_total` y `neto`. Expone además `ganancia_divisas`
> (suma de la ganancia FIFO de las ventas de USD — ver §4) y `saldo_pasivos` (snapshot de
> `PENDIENTE` por moneda, sin filtro de período). Ya **no existe** el endpoint devengado
> `…/ganancias`. El frontend consume `/reportes/caja` (`frontend/src/api/reportes.ts`).
>
> **Todas las reglas del régimen de caja diaria están implementadas y verificadas (2026-06-26)**
> y asientan en este mismo libro: préstamos (egreso al originar, ingreso al cobrar — §3), cálculo
> FIFO de divisas (§4), gastos por moneda restando el neto de su moneda (§6) y el vuelto de pasivos
> pagados con cheque "de más" (§5).

### 7.b Ajustes manuales de caja

Agregar o restar efectivo a mano, sin operación de negocio detrás. Ver
**§Ajustes de caja** para el régimen completo (motivos, tratamiento en el reporte y
lo que hay que respetar al tocar dólares).

---

### 8. Backup / Configuración _(módulo agregado)_

- Página **Configuración** del panel web: apertura del sistema (§Apertura, componente
  `AperturaSistema`), gestión de usuarios y export/import de datos.
- `GET /api/v1/backup/exportar`: snapshot completo en JSON (incluye fotos de cheques embebidas).
  **Conserva los registros anulados con su marca** — es una copia fiel de la base; si no los
  llevara, un ciclo export→import los resucitaría.
- **Las listas `_CL`/`_CH`/… fijan qué columnas viajan, y tienen que estar completas.** Una
  columna que falta no rompe el export: el daño aparece al importar, **en silencio** (vuelve
  en NULL o en su default). Ya pasó con `es_carga_inicial` —la cartera preexistente volvía como
  compra normal y se le asentaba el egreso que §Apertura quita, o sea plata descontada dos
  veces—, con `es_apertura`/`es_ajuste` y con `medio_pago`/`cotizacion`. `test_backup_columnas.py`
  compara cada lista contra su modelo, así que **una migración que agregue una columna hace
  fallar el test** y obliga a decidir si va al backup. Si es Decimal, además va en `_DEC_COLS`:
  sin eso se inserta como texto y el descuadre recién se nota al sumar la caja.
- `GET /api/v1/backup/exportar-excel`: export a XLSX (filtrable por día local ART). **Excluye los
  anulados** (y las cuotas de préstamos anulados): es un reporte de trabajo, no una copia.
- `POST /api/v1/backup/importar`: import con **validación de schema** antes de aplicar.

### 9. Autenticación / Usuarios _(módulo agregado 2026-06-19)_

- Login **por usuario+contraseña** para el panel. La validación es **en el backend**: todos los
  routers de negocio van con `dependencies=[Depends(get_current_user)]` en `app/main.py`. **Públicos:**
  `health.router` (`/health` y `/health/deep`, este último con su propio `HEALTH_TOKEN` — ver §10),
  `auth.router`, el `webhook` de WhatsApp y `cheques.public_router` (solo `GET /cheques/{id}/foto`; ver Chequera Virtual).
- **Sesión sin caducidad por tiempo:** el JWT (HS256, `app/core/auth.py`) **no lleva `exp`**; lleva
  `sub` + `ver`. La revocación es por BD: `get_current_user` exige `usuario.activo` y que `ver` del
  token coincida con `usuario.token_version`. Resetear/recuperar la clave **incrementa `token_version`**
  → mata las sesiones viejas. El token se guarda en `localStorage` del front (`auth_token`).
- **Alta por invitación (no registro abierto):** un **admin** invita (`POST /api/v1/invitaciones`
  `{phone, is_admin}`); se genera un **enlace de un solo uso** (vence 24 h) que se envía por WhatsApp
  con `send_text` y también se devuelve en la respuesta. La persona abre `/registro?token=...`,
  `POST /api/v1/auth/registrar` crea la cuenta (auto-login) y marca la invitación usada.
- **Recuperación de clave por WhatsApp:** `POST /api/v1/auth/forgot-password {username}` → código OTP
  de 6 dígitos (hash bcrypt + vence ~10 min) enviado por WhatsApp; responde **siempre 200 genérico**
  (no revela si el usuario existe). `POST /api/v1/auth/reset-password {username, code, new_password}`.
  **Reseteo por admin** (respaldo, sin WhatsApp): `PATCH /api/v1/usuarios/{id} {reset_password:true}`
  genera una **clave temporal** que se devuelve al admin para comunicarla.
- **Admin raíz:** se bootstrapea en el `startup` de `main.py` desde `ADMIN_USERNAME`/`ADMIN_PASSWORD`
  (idempotente; si se cambia la env var y se reinicia, re-sincroniza la clave → siempre recuperable).
- **Solo admin** (`require_admin`, 403 si no): invitar/revocar, listar usuarios, `PATCH` (reset clave,
  activar/desactivar, cambiar rol, editar teléfono). Salvaguarda: no se puede dejar el sistema sin
  ningún admin activo. El `username` se guarda **siempre en minúsculas** (unicidad case-insensitive).
- **Frontend:** `AuthContext` (`frontend/src/auth/AuthContext.tsx`) + `ProtectedRoute` (guard;
  `/usuarios` es `adminOnly`). `apiFetch` (`api/client.ts`) inyecta el Bearer y, ante **401** en ruta
  protegida, limpia el token y vuelve a `/login`. En `VITE_MOCK=1` el `AuthContext` cortocircuita con
  un admin mock para que la demo siga navegable sin backend.

### 10. Monitoreo de salud y alertas _(módulo agregado 2026-08-13)_

El bot se cayó una vez y **se enteró antes el cliente que nosotros**. Esta capa
existe para que eso no vuelva a pasar: vigila las piezas, y cuando algo se rompe
avisa **por Telegram** diciendo **qué** se rompió.

- **Telegram y no WhatsApp, a propósito.** La caída más común es que la sesión de
  WhatsApp se desvincule del celular; avisar por el canal que se cayó es imposible.
  `services/telegram.py` es el único canal de alerta y **nunca lanza**: una alerta
  que revienta el proceso que intentaba alertar es peor que no tenerla.
- **Cuatro piezas, no una** (`services/health.py`, todas en el mismo diagnóstico):
  `base_datos` (`SELECT 1`), `waha` (el gateway responde), `sesion_wa` (el `status`
  de la sesión) y `webhook_wa`. Cada chequeo trae su `detalle` en castellano y ese
  texto va tal cual al mensaje: tiene que decirle qué hacer a quien lo lee a las 3 AM.
  - **`webhook_wa` es el que atrapa la caída silenciosa:** sesión `WORKING`, gateway
    sano y ni un mensaje llegando porque WAHA se reinició sin su config de webhook.
    Desde afuera el bot parece perfecto. Compara contra `PUBLIC_BASE_URL` y es
    **tolerante**: si la respuesta de WAHA no trae `config.webhooks` devuelve OK en
    vez de inventar una caída permanente.
  - `SCAN_QR_CODE`/`FAILED`/`STOPPED` son **CAIDO**; `STARTING` es solo `DEGRADADO`
    (es transitorio: tratarlo como caída daría un falso positivo en cada deploy).
- **Dos capas de vigilancia, y sacar una deja un agujero:**
  - **Interna** (`services/monitor.py`): tarea de fondo del backend, cada
    `MONITOR_INTERVALO_SEGUNDOS`. Ve todo lo que rodea al proceso, pero **no puede
    avisar si el proceso muere**. Asume **un solo worker de uvicorn** (lo que hace
    `entrypoint.sh`); con varios workers cada uno alertaría por su cuenta.
  - **Externa** (`.github/workflows/healthcheck.yml`): cron de GitHub Actions cada
    5 min contra `GET /health/deep`. Es la única que detecta "Railway tumbó el
    servicio". El cron de GitHub es *best effort* y puede correrse unos minutos.
- **`/health` y `/health/deep` no son lo mismo y confundirlos rompe el deploy.**
  `/health` es el healthcheck de Railway (`railway.toml`): trivial, 200 mientras el
  proceso viva. Si devolviera error porque WAHA está caído, Railway daría el deploy
  por fallido y **reiniciaría el backend en loop** por un problema ajeno.
  `/health/deep` es el diagnóstico completo y devuelve **503 cuando algo está CAIDO**
  para que cualquier monitor de uptime lo note sin leer el cuerpo.
  - **El `HEALTH_TOKEN` decide cuánto se cuenta, no si se responde.** Con token válido
    (`X-Health-Token`, o `?token=` que queda escrito en los access logs) vienen los
    `detalle` de cada pieza; sin token válido —o con la env var sin configurar— va el
    mismo estado **sin detalles**, que cuentan a qué URL apunta el webhook y qué host
    de Postgres no contesta. Así olvidarse de configurarlo no abre la infra. Se compara
    con `secrets.compare_digest`.
  - **Los detalles que salen del sistema van sin datos crudos:** el chequeo de BD
    publica el tipo de excepción, no el texto de psycopg (que trae host, puerto y
    usuario), y la alerta de error del webhook manda `archivo:línea` en vez del
    traceback — el mensaje de una excepción de SQLAlchemy arrastra el SQL con sus
    parámetros (montos, clientes, teléfonos) y Telegram es un tercero. El detalle
    completo se loguea, que es donde se debuggea.
- **La alerta tiene que significar algo** (`health.decidir_alerta`, función pura y
  testeada): no avisa al primer fallo (`MONITOR_UMBRAL_FALLOS`, un timeout suelto se
  recupera solo), no repite la misma caída salvo cada `MONITOR_REPETIR_MINUTOS`,
  avisa **enseguida si cambia qué está roto**, y siempre anuncia la recuperación —
  pero solo si había una alerta abierta. Una alerta que suena por ruido se ignora, y
  la próxima caída real la descubre otra vez el cliente.
- **Además del chequeo periódico se alerta en el momento** en dos lugares donde el
  operador se queda esperando: `send_text` que no se puede entregar
  (`_alertar_no_entregado`) y una excepción no controlada procesando un mensaje
  (`webhook._procesar_mensaje_safe`, con traceback). Van por `monitor.alertar_error`,
  que agrupa por `clave` y no repite el mismo error dentro de 15 min: un problema
  sistemático llenaría el chat y taparía lo demás.
- **Env vars:** `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS` (coma-separados),
  `HEALTH_TOKEN` y los `MONITOR_*`. Sin token de Telegram el monitor **no arranca**
  (lo loguea); el resto sigue funcionando igual.
- **Tests:** `test_health.py`, unitario puro — interpretación de los estados de WAHA,
  el chequeo de webhook y toda la máquina de `decidir_alerta`.

---

## Bot WhatsApp

- **Ruteo de modelos por tarea (`services/ia/claude.py`, definido 2026-08-10).** El bot tiene
  dos cargas de trabajo con perfiles de riesgo opuestos y se rutean según **si el mensaje trae
  foto** — señal disponible antes de llamar (`image_bytes`):
  - `_MODEL_OCR = claude-opus-5` (effort `medium`) — mensajes **con foto**. Es la parte cara de
    equivocarse: un dígito mal leído es plata mal cargada. **Este camino no se abarata ni lleva
    escalada.** Un error de OCR no lanza excepción ni devuelve señal: entrega un JSON impecable
    con el número equivocado, así que no hay falla que detectar ni a qué reintentar.
  - `_MODEL_TEXTO = claude-sonnet-5` (effort `low`) — mensajes **de solo texto**, el grueso del
    volumen (cobros, gastos, ventas, consultas). Acá el error se ve —el bot muestra la operación
    y el operador la corrige— y además hay escalada, así que el modelo barato es una apuesta
    acotada. Hasta el commit `0acab9f` este camino corría en Sonnet 4.6 sin razonamiento.
  - `_MODEL_CONFIRMACION = claude-haiku-4-5` — solo clasifica "dale"/"no", y únicamente cuando
    la lista local `_CONFIRM_WORDS` del webhook no reconoce el modismo.
- **Escalada solo ante señal confiable.** `_extraer_con_modelo` devuelve `None` ante una falla
  **dura** (JSON ilegible, `refusal`, error de red); el camino de texto reintenta con
  `_MODEL_OCR` ante ese `None` o ante un `DESCONOCIDO`. **No escala en `ACLARACION_REQUERIDA`:**
  pedir un dato que el operador realmente no dijo es la respuesta correcta, y escalar ahí
  duplicaría el costo de un caso que funcionó bien.
- **Prompt caching del system prompt.** Son ~5.900 tokens idénticos en cada mensaje: van en un
  bloque con `cache_control: ephemeral`, y una lectura cacheada cuesta ~10% de la entrada. El
  caché es un match de **prefijo**: interpolar algo variable ahí (fecha, nombre del operador) lo
  rompe **sin dar error** — solo se nota en los contadores que loguea `_loguear_uso_cache`
  (`cache leido` en 0 mensaje tras mensaje). El TTL es de 5 min: conviene con mensajes en tanda,
  y un mensaje aislado sale ~25% más caro. El clasificador de confirmación **no** se cachea:
  su prompt son ~300 tokens y Haiku exige 4.096 como mínimo.
- Dos cosas más que hay que respetar al tocar esas llamadas:
  - **El razonamiento está activo por defecto** en estos modelos y `max_tokens` es el tope de
    *razonamiento + respuesta juntos*. Con un cap chico el JSON sale truncado (por eso 8192,
    no 1024). Es un techo, no un cargo: solo se paga lo que se genera.
  - **`content[0]` puede ser un bloque `thinking`**, no el texto: leer por índice devuelve
    basura. Usar `_texto_de(response)`.
- **Multi-cheque (§ punto 1, 2026-08-06): una foto puede traer varios cheques.**
  `REGISTRAR_CHEQUE` devuelve `data.cheques` (ARRAY) y `VENDER_CHEQUE` devuelve `data.ventas`
  (ARRAY), siempre — con un solo cheque el array trae un elemento. `_items_o_uno()` normaliza
  y **tolera el formato viejo** de campos sueltos, para que una sesión abierta con historial
  del contrato anterior no se rompa a mitad de conversación.
  - **Porcentaje:** uno solo mencionado con varios cheques se aplica a todos; varios se
    asignan en orden; si no lo aclara y hay más de uno → `ACLARACION_REQUERIDA` (no se inventa).
  - **Fallo parcial: se cargan los válidos y se informa cuál falló** (decisión del dueño), en
    vez de abortar el lote — así no hay que repetir la foto de los cuatro por uno duplicado.
    Cada alta commitea por separado, que es lo que hace posible ese comportamiento.
- El bot opera vía WAHA (WhatsApp HTTP API) → webhook `POST /webhook/whatsapp`.
- Solo el número configurado en `WHATSAPP_OPERATOR_PHONE` puede operar.
- Flujo: mensaje → parser → (audio: Whisper) → Claude → dispatcher → BD → respuesta WA.
- La sesión de Claude **se limpia tras cada transacción exitosa** (Regla de Limpieza).
- Los **pasivos** se pueden registrar desde el bot via `REGISTRAR_DEUDA`; la cancelación es solo desde el panel web.
- Los **gastos operativos** sí son registrables desde el bot via intent `REGISTRAR_GASTO` (editables por concepto/hora/monto desde el chat).
- Los **fiados** son operables desde el bot: `FIAR_CHEQUE`, `COBRAR_FIADO_EFECTIVO`, `COBRAR_FIADO_CON_CHEQUE`.

**Intents soportados por el dispatcher** (`services/whatsapp/dispatcher.py`):
- Cheques: `REGISTRAR_CHEQUE`, `VENDER_CHEQUE`, `FIAR_CHEQUE`, `COBRAR_CHEQUE`, `RECHAZAR_CHEQUE`.
- Préstamos: `NUEVO_PRESTAMO`, `COBRAR_CUOTA`.
- Fiados: `COBRAR_FIADO_EFECTIVO`, `COBRAR_FIADO_CON_CHEQUE`.
- Otros: `REGISTRAR_DEUDA`, `MOVIMIENTO_EFECTIVO`, `REGISTRAR_GASTO`, `EDITAR_OPERACION`,
  `REVERTIR_OPERACION`.
  - **`REVERTIR_OPERACION` deshace; `EDITAR_OPERACION` corrige.** Editar cambia un valor mal
    cargado ("el % era 3 no 2"); revertir deshace la operación entera ("no se vendió",
    "borrá eso"). El prompt marca la diferencia explícitamente y hay un test que la custodia.
  - `accion: REVERTIR` (solo cheques → vuelven a `EN_CARTERA` sin eliminarse) o `ELIMINAR`
    (anula y revierte la caja). Ambas delegan en `svc_anulacion`, así que **las reglas de
    bloqueo son las mismas que en el panel** — un fiado con cobros encima o una venta de USD
    que no es la última se rechazan igual desde el chat.
  - Siempre pide **confirmación** (`confirmacion_requerida: true`): es destructiva.
- Consultas (lectura): `CONSULTA_CARTERA`, `CONSULTA_CLIENTE`, `CONSULTA_PRESTAMOS`.

---

## Reglas de código

- No existe facturación, AFIP, impuestos ni campos fiscales en ninguna tabla. No los agregues.
- Los cheques y divisas son **inventario físico interno**, no instrumentos financieros regulados.
- Los ENUMs de PostgreSQL se crean en las migraciones Alembic con `create_type=False` en los modelos.
- Cada tabla tiene trigger `updated_at` vía `fn_set_updated_at()` (creada en migración 0001).
- Las transacciones críticas usan `SELECT ... FOR UPDATE` para evitar race conditions.
- **Fechas/horas en hora local de Argentina (ART), no UTC.** Usar los helpers de `app/core/fechas.py` (`hoy_local`, etc.); los gastos guardan `hora_operacion` (migración `0008`).
- **Naming Pasivos vs Deudas:** el módulo se llama **Pasivos** en backend/BD/API, pero en el navbar del frontend aparece rotulado como **"Deudas"**. Es la misma entidad.
- **Sección "Deudores" (frontend):** agrupa lo que los **clientes** le deben al negocio (≠ "Deudas"/Pasivos, que es al revés). Cuatro pestañas: **General** (índice, `/deudores` → `DeudoresGeneral`), **Préstamos** (`/deudores/prestamos`), **Cheques fiados** (`/deudores/cheques-fiados`) y **Otras deudas** (`/deudores/otras` → `DeudoresOtras`, las deudas simples — ver §2.b). La pestaña **General** es una **vista consolidada por cliente** (total ARS y USD sumando préstamos + fiados + deudas simples) armada **en el front** desde `/prestamos`, `/fiados` y `/deudas-simples` (no hay endpoint de agregación); tiene un botón **"Nuevo"** que abre `ModalNuevaDeudaSimple`. El **pago de importe libre** (parcial o total, cross-currency) vive en el componente compartido `components/ModalPagarDeuda.tsx` (llama a `pagar_prestamo`, `cobrar_con_efectivo` o `cobrar_deuda_simple` según el `tipo` de deuda) y se usa en General, Préstamos y Otras deudas (botón "Pago libre"/"Cobrar", además del cobro por cuota entera). No reemplaza el cobro directo desde las otras pestañas.

---

## Testing

- Los tests (`backend/tests/`) son **unitarios puros**: ejercitan la lógica de negocio
  en memoria, **sin base de datos ni fixtures** (por eso no hay `conftest.py`). Cada test
  arma sus objetos con instancias de modelo o funciones puras y, donde hace falta una sesión,
  usa un stub mínimo (`FakeDB`). Se corren con `pytest` desde `backend/`.
- Suites:
  - **`test_business_rules.py`** — máquina de estados de cheques (transiciones válidas y
    terminales, exige `operador_id`+`motivo`, spread de venta) y armado del cuadro de cuotas
    (`construir_cuotas`: fechas por frecuencia/fin de mes y centavo sobrante en la última).
  - **`test_caja_divisas.py`** — ganancia **FIFO** de divisas (`calcular_ganancia_fifo`):
    consumo de lotes en orden, ventas parciales que cruzan lotes, venta a pérdida y stock
    insuficiente (`ValidationError`).
  - **`test_auth.py`** — hash de contraseñas, JWT sin `exp` (`sub`+`ver`), `get_current_user`
    (inactivo / `token_version` desfasado → 401), `require_admin`, OTP e invitaciones.
  - **`test_resolucion_clientes.py`** — desambiguación de clientes por nombre en el bot
    (`_elegir_cliente_match`): atajo de match exacto, modo `estricto` en cobros y casos límite.
  - **`test_pasivos_pago.py`** — `conversion.calcular_reduccion_saldo`: mismo/otra moneda,
    tolerancia de un centavo y pago que supera el saldo.
  - **`test_prestamos_pago.py`** — `repartir_pago_en_cuotas` (imputación a la cuota más vieja
    primero, parcial/total, saltea saldadas, no reparte de más) + cross-currency del préstamo.
  - **`test_deudas_simples.py`** — `aplicar_cobro` de una deuda simple (§2.b): nuevo saldo y
    transición a cancelada en cobros parciales/totales, sin dejar saldo negativo.
  - **`test_anulacion.py`** — reglas de bloqueo del motor de anulación (§Anulación): fiado con
    cobros encima, cheque usado para pagar un pasivo, compra de USD ya consumida y venta que no
    es la última. Incluye dos tests que **custodian el catálogo `_ENTIDADES`**: si una entidad
    perdiera alguna `referencia_tipo`, la anulación dejaría líneas de caja vivas contando plata
    que ya no existe, y eso pasaría desapercibido.
  - **`test_backup_columnas.py`** — custodia que cada lista de columnas del export cubra
    **todas** las del modelo (§8). Falla a propósito cuando una migración agrega una columna
    nueva: es el único aviso de que el import la devolvería vacía sin decir nada.
  - **`test_ajustes_caja.py`** — ajustes manuales (§Ajustes de caja): el consumo FIFO de
    un ajuste que resta USD (`consumir_lotes_fifo`, que es la misma primitiva que usa la
    venta) y las reglas de bloqueo de `_validar_ajuste` al anular uno en dólares.
  - **`test_health.py`** — capa de salud (§10): cómo se lee cada estado de sesión de WAHA,
    el chequeo del webhook (incluida la tolerancia a respuestas sin `config`) y la máquina
    de `decidir_alerta` — que no avise al primer fallo, que no repita, que avise enseguida
    si cambia qué está roto y que anuncie la recuperación.
  - **`test_apertura.py`** — fecha de corte de la carga inicial (§Apertura): el día del corte es
    inclusive, después vuelve a descontar, y sin corte definido todo es operación normal. Fija
    además que `SALDO_INICIAL` va al grupo `APERTURA` y no cuenta como ingreso del día.
- **Convención:** mantené la lógica de negocio en funciones/métodos testeables sin BD; si una
  pieza nueva necesita una sesión, extraé la parte pura para poder cubrirla en este estilo.

---

## Migraciones (Alembic)

- Las migraciones viven en `backend/alembic/versions/`, numeradas **secuencialmente**
  `0001`…`NNNN`. El `revision` y el `down_revision` forman una **cadena lineal** (p. ej. el
  `down_revision` de `0013` es `0012`); una migración nueva hereda como `down_revision` el head anterior.
- **Nunca editar una migración ya aplicada en prod (Railway).** Para cualquier cambio de schema,
  creá **una migración nueva** con el siguiente número, no modifiques una existente.
- Los **ENUM de PostgreSQL** se crean dentro de la migración; los modelos los referencian con
  `create_type=False` para que SQLAlchemy no intente recrearlos (ver también §Reglas de código).
- Aplicar con `alembic upgrade head`.

---

## Comandos frecuentes

```powershell
# Activar venv
cd backend
.\.venv\Scripts\Activate.ps1

# Instalar dependencias
pip install -r requirements-dev.txt

# Migrar BD
alembic upgrade head

# Correr API local
uvicorn app.main:app --reload

# Tests
pytest
```

---

## Variables de entorno requeridas

Ver `backend/.env.example`. Las críticas para producción:

- `DATABASE_URL`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY` (Whisper, para transcribir audios)
- `WAHA_API_URL` / `WAHA_API_KEY` / `WAHA_SESSION` (gateway WhatsApp, engine NOWEB)
- `WHATSAPP_OPERATOR_PHONE` (solo dígitos, sin `@s.whatsapp.net`)
- `SECRET_KEY` (firma de los JWT de sesión — **obligatoria en prod**, larga y aleatoria)
- `ADMIN_USERNAME` / `ADMIN_PASSWORD` (admin raíz bootstrapeado al arranque)
- `PUBLIC_BASE_URL` (opcional; base para los enlaces de invitación, sin barra final)
