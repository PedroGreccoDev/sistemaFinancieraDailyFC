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
- La ganancia del préstamo se calcula como `total_a_cobrar - credito`.
- El préstamo pasa a estado `CANCELADO` automáticamente cuando se cobra la última cuota.
- El monto de cada cuota se divide uniformemente; el centavo sobrante cae en la **última** cuota.

**Cobro de cuotas desde el panel web** (además del bot, intent `COBRAR_CUOTA`):
- Cobro simple (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobros`.
- Cobro simple en lote (multi-selección): `POST /prestamos/{id}/cuotas/cobrar-lote`.
- Cobro con cheque (1 cuota): `POST /prestamos/{id}/cuotas/{cuota_id}/cobrar-con-cheque` — genera un cheque `EN_CARTERA`.
- Cobro con cheque en lote: `POST /prestamos/{id}/cuotas/cobrar-con-cheque-lote`.
- **Método de pago "Efectivo" vs "Transferencia" es solo una etiqueta de UI**: el backend NO persiste el medio; solo distingue cobro simple (sin cheque) vs cobro con cheque.

### 4. Movimientos de Efectivo

- Operaciones de compra/venta de divisas (ARS ↔ USD).
- **Regla crítica:** la cotización **siempre** la dicta el operador. El sistema jamás la asume ni la consulta.
- El widget de Dólar Blue en el frontend es **solo decorativo** (consume DolarAPI externamente).

### 5. Pasivos _(módulo agregado 2026-06-08)_

- Registro de **deudas del negocio** con clientes y proveedores (cuentas a pagar).
- **Alta** via bot de WhatsApp (intent `REGISTRAR_DEUDA`) o desde el panel web (botón "Nueva deuda").
- El bot **exige** que el operador indique el concepto; si falta, responde con `ACLARACION_REQUERIDA`.
- **Cancelación** solo desde el panel web (el bot no puede cancelar pasivos).
- Estados: `PENDIENTE` → `CANCELADA` (transición única, irreversible).
- **Pagos parciales:** el pasivo tiene `saldo_pendiente` (migración `0007`); se puede cancelar en partes, en efectivo o con un cheque de cartera. Pasa a `CANCELADA` cuando el saldo llega a 0.
- Campos: `acreedor`, `concepto`, `monto`, `moneda`, `fecha_vencimiento` (opcional).
- El cierre de caja incluye un snapshot de pasivos pendientes por moneda, **sin filtro de periodo**.
- No existe facturación ni concepto fiscal asociado.

### 6. Gastos Operativos _(módulo agregado 2026-06-08)_

- Registro de gastos de caja del negocio (nafta, insumos, comida, parking, etc.).
- **Carga via bot de WhatsApp** (intent `REGISTRAR_GASTO`) o manual vía API.
- Campos: `concepto`, `monto`, `moneda` (default ARS), `fecha_operacion`, `observaciones`.
- Se descuentan del bruto en el reporte de ganancias para obtener el **neto del período**.

### 7. Reportes y Cierre de Caja

- El endpoint `GET /api/v1/reportes/ganancias?desde=&hasta=` consolida:
  - Ganancias de cheques (por `ultimo_evento_manual_at` dentro del periodo).
  - Ganancias de préstamos (por `created_at` del préstamo).
  - Ganancias de movimientos de efectivo (por `fecha_operacion`).
  - `cobros_cuotas_ars` / `cobros_cuotas_usd`: cobros de cuotas en el periodo, por moneda.
  - `gastos_operativos`: suma de gastos ARS en el periodo.
  - `saldo_pasivos`: snapshot de pasivos PENDIENTE (no filtrado por periodo).
- `total_ganancias` = suma bruta de ganancias; `neto` = total_ganancias − gastos_operativos.
- `GET /api/v1/reportes/cobros-cuotas?desde=&hasta=` devuelve el historial detallado de cuotas cobradas.
- El historial unificado de Movimientos (frontend) incluye también los cobros de cuotas y los gastos.

### 8. Backup / Configuración _(módulo agregado)_

- Página **Configuración** del panel web con export/import de datos.
- `GET /api/v1/backup/exportar`: snapshot completo en JSON (incluye fotos de cheques embebidas).
- `GET /api/v1/backup/exportar-excel`: export a XLSX (filtrable por día local ART).
- `POST /api/v1/backup/importar`: import con **validación de schema** antes de aplicar.

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
