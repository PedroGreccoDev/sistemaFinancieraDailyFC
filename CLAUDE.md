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

### 2. Fiados _(módulo agregado 2026-06-09)_

Cuando se **fía** un cheque se genera una **deuda abierta** del cliente, sin cuotas fijas.

**Saldo inicial:** `monto_cheque × (1 − porcentaje_venta / 100)`
(el porcentaje_venta es el descuento pactado al entregar el cheque).

El cliente puede cancelar esa deuda de dos formas:

**a) En efectivo:**
- Se registra con `POST /fiados/{id}/cobrar-efectivo` (`monto_cobrado`).
- El monto debe ser ≤ `saldo_pendiente`. Se puede pagar en partes.
- Cuando `saldo_pendiente` llega a 0, el fiado pasa a `CANCELADO`.

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

### 3. Préstamos y Cuotas _(sin cheque asociado)_

- Monedas soportadas: `ARS` y `USD`.
- Frecuencias: `diaria | semanal | quincenal | mensual | anual`.
- La ganancia teórica del préstamo es `total_a_cobrar - credito` (se guarda como referencia).
- El préstamo pasa a estado `CANCELADO` automáticamente cuando se cobra la última cuota.
- El monto de cada cuota se divide uniformemente; el centavo sobrante cae en la **última** cuota.
- **Reconocimiento en caja (régimen caja diaria, definido 2026-06-25):** el ingreso se
  cuenta **al cobrar cada cuota, NO al originar el préstamo**. Cada cuota cobrada suma a la
  caja diaria del día del cobro, con detalle de cliente/préstamo/cuota. El otorgamiento del
  crédito es un **egreso** del día en que se da. _(Implementación pendiente: hoy el reporte
  suma la ganancia entera por `created_at` del préstamo — ver §7.)_

**Cobro de cuotas desde el panel web** (además del bot, intent `COBRAR_CUOTA`):
- Cobro simple (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobros`.
- Cobro simple en lote (multi-selección): `POST /prestamos/{id}/cuotas/cobrar-lote`.
- Cobro con cheque (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobrar-con-cheque` — genera un cheque `EN_CARTERA`.
- Cobro con cheque en lote: `POST /prestamos/{id}/cuotas/cobrar-con-cheque-lote`.
- **Método de pago "Efectivo" vs "Transferencia" es solo una etiqueta de UI**: el backend NO persiste el medio; solo distingue cobro simple (sin cheque) vs cobro con cheque.

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
  _(Implementación pendiente: hoy `ganancia` se acepta del payload sin calcularse y no hay lotes.)_
- El widget de Dólar Blue en el frontend es **solo decorativo** (consume DolarAPI externamente).

### 5. Pasivos _(módulo agregado 2026-06-08)_

- Registro de **deudas del negocio** con clientes y proveedores (cuentas a pagar).
- **Alta** via bot de WhatsApp (intent `REGISTRAR_DEUDA`) o desde el panel web (botón "Nueva deuda").
- El bot **exige** que el operador indique el concepto; si falta, responde con `ACLARACION_REQUERIDA`.
- **Cancelación** solo desde el panel web (el bot no puede cancelar pasivos).
- Estados: `PENDIENTE` → `CANCELADA` (transición única, irreversible).
- **Pagos parciales:** el pasivo tiene `saldo_pendiente` (migración `0007`); se puede cancelar en partes, en efectivo o con un cheque de cartera. Pasa a `CANCELADA` cuando el saldo llega a 0.
- **Pago con cheque "de más" (régimen definido 2026-06-25):** cuando el valor neto del cheque
  supera el saldo del pasivo, el operador elige qué hacer con el vuelto:
  **(a)** paga la diferencia al cliente en efectivo/transferencia y queda saldada, o
  **(b)** el negocio queda debiendo → se crea **automáticamente un pasivo a favor del cliente**
  por el monto del vuelto. _(Implementación pendiente: hoy el excedente se descarta.)_
- Campos: `acreedor`, `concepto`, `monto`, `moneda`, `fecha_vencimiento` (opcional).
- El cierre de caja incluye un snapshot de pasivos pendientes por moneda, **sin filtro de periodo**.
- No existe facturación ni concepto fiscal asociado.

### 6. Gastos Operativos _(módulo agregado 2026-06-08)_

- Registro de gastos de caja del negocio (nafta, insumos, comida, parking, etc.).
- **Carga via bot de WhatsApp** (intent `REGISTRAR_GASTO`) o manual vía API.
- Campos: `concepto`, `monto`, `moneda` (default ARS), `fecha_operacion`, `observaciones`.
- Se descuentan como **egreso** en el reporte para obtener el **neto del período**.
- **Por moneda (régimen definido 2026-06-25):** un gasto en USD resta del **neto USD** y un gasto
  en ARS resta del **neto ARS**. La caja se lleva separada por moneda. _(Implementación pendiente:
  hoy el reporte solo resta los gastos ARS y el neto es único.)_

### 7. Reportes y Cierre de Caja

**Modelo objetivo (caja diaria, definido 2026-06-25):** el reporte es una **caja de flujo real
de ingresos y egresos efectivos, separada por moneda (ARS y USD)** — NO un P&L devengado. Para
cada moneda: `neto = Σ ingresos − Σ egresos` del período. Cada línea va detallada (origen,
cliente, operación, fecha).

- **Ingresos (entra plata):** cuotas de préstamo cobradas (al cobrar, incluidos cobros parciales),
  cobros de fiado en efectivo (incluidos parciales), ventas de cheques, ventas de USD (pesos
  recibidos) y su ganancia FIFO.
- **Egresos (sale plata):** gastos diarios, compra de cheques, compra de USD (pesos que salen),
  compra de cualquier activo y otorgamiento de préstamos (crédito entregado).
- **Cobros parciales cuentan:** si de un fiado de $100.000 entran $100, esos $100 son ingreso
  del día con su detalle (fiado, cliente, fecha).
- `GET /api/v1/reportes/cobros-cuotas?desde=&hasta=` devuelve el historial detallado de cuotas cobradas.
- El historial unificado de Movimientos (frontend) incluye también los cobros de cuotas y los gastos.

> ⏳ **Estado de implementación:** el endpoint actual `GET /api/v1/reportes/ganancias` todavía
> funciona en modo devengado y NO cumple este modelo. Hoy consolida:
> - Ganancias de cheques (por `ultimo_evento_manual_at`), préstamos (por `created_at` del préstamo)
>   y movimientos (por `fecha_operacion`); `total_ganancias` = suma bruta; `neto` = total − gastos ARS.
> - `cobros_cuotas_ars` / `cobros_cuotas_usd` (informativos, no sumados), `saldo_pasivos` (snapshot
>   de PENDIENTE sin filtro de período).
>
> Migrar a caja diaria por moneda implica: ingreso de préstamos al cobrar (no al originar),
> egresos (crédito, compras de cheque/USD), ganancia FIFO de divisas y netos ARS/USD separados.

### 8. Backup / Configuración _(módulo agregado)_

- Página **Configuración** del panel web con export/import de datos.
- `GET /api/v1/backup/exportar`: snapshot completo en JSON (incluye fotos de cheques embebidas).
- `GET /api/v1/backup/exportar-excel`: export a XLSX (filtrable por día local ART).
- `POST /api/v1/backup/importar`: import con **validación de schema** antes de aplicar.

### 9. Autenticación / Usuarios _(módulo agregado 2026-06-19)_

- Login **por usuario+contraseña** para el panel. La validación es **en el backend**: todos los
  routers de negocio van con `dependencies=[Depends(get_current_user)]` en `app/main.py`. **Públicos:**
  `/health`, `auth.router` y el `webhook` de WhatsApp.
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

---

## Bot WhatsApp

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
- Otros: `REGISTRAR_DEUDA`, `MOVIMIENTO_EFECTIVO`, `REGISTRAR_GASTO`, `EDITAR_OPERACION`.
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
