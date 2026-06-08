# CLAUDE.md

Guía para trabajar en este repositorio. Lee esto antes de hacer cambios.

## Qué es

Sistema de gestión para una **financiera informal** ("cueva"). El operador maneja
todo por **WhatsApp** (texto, audio, fotos de cheques); la IA extrae los datos y
hace la matemática, pero **el operador siempre confirma**. Hay además un dashboard
web (React) para arqueo, cartera y reportes.

**Regla de oro del negocio:** cero facturación, cero AFIP. Cheques y divisas son
**stock/inventario físico**. Ninguna tabla o lógica debe incluir conceptos de
facturación/blanqueo (ej. nada de `incluir_factura`).

**Human in the loop:** la IA nunca asume cotizaciones ni cambia estados sin orden
explícita del operador. Las cotizaciones las dicta siempre el operador.

## Stack

- **Backend:** FastAPI (Python), SQLAlchemy + Alembic, PostgreSQL.
- **Frontend:** React + Vite + TailwindCSS.
- **Infra:** monorepo en **Railway** (build por `backend/Dockerfile`, ver `railway.toml`).
- **WhatsApp:** **WAHA** (WhatsApp HTTP API — gateway no oficial, engine NOWEB).
  Webhook directo a FastAPI.
- **IA visión/razonamiento:** Claude (Anthropic) — `app/services/ia/claude.py`.
- **IA transcripción de audio:** Whisper (OpenAI) — `app/services/ia/whisper.py`.

> Nota histórica: se usó Evolution API y se intentó migrar a la Cloud API oficial de
> Meta (commit `b2f662c`, revertido en `e0ff326`). Se eligió **WAHA** porque a este
> volumen (≈25 msj/día, 2 números, horario humano) el ban no es el riesgo real, y su
> engine `NOWEB` (sin Chromium) evita el problema de Evolution de no generar el QR.
> Al ser gateway no oficial, **no hay ventana de 24h ni plantillas**: se manda texto
> libre siempre.

## Estructura

```
backend/app/
  main.py                  # FastAPI app, routers, healthcheck, SPA fallback
  core/config.py           # Settings (pydantic-settings, lee .env / env de Railway)
  api/routes/              # Endpoints REST + webhook de WhatsApp
    webhook.py             # POST: mensajes entrantes de WAHA
  services/
    whatsapp/
      client.py            # Envío de texto y descarga de media (WAHA)
      parser.py            # Normaliza el payload del webhook -> IncomingMessage
      dispatcher.py        # Aplica el intent extraído sobre la BD
      session.py           # Historial corto en memoria + pending intents
    ia/claude.py           # Extracción de intención (texto/imagen + historial)
    ia/whisper.py          # Transcripción de notas de voz
    cheques.py / prestamos.py / movimientos.py / clientes.py / reportes.py
  db/models.py             # Modelos SQLAlchemy
  schemas/                 # Esquemas Pydantic de la API REST
frontend/src/
  pages/                   # Cartera, Deudores, Movimientos, Reportes, Dashboard
  api/                     # Clientes HTTP al backend + DolarAPI (dólar blue)
```

## Comandos

```bash
# Backend (desde backend/)
pip install -r requirements.txt -r requirements-dev.txt
alembic upgrade head            # migraciones
uvicorn app.main:app --reload   # dev server (localhost:8000)
pytest                          # tests (ver tests/test_business_rules.py)

# Frontend (desde frontend/)
npm install
npm run dev                     # Vite dev server
npm run build                   # genera el build que sirve FastAPI en prod

# Todo junto (local)
docker-compose up               # db + backend
```

## Pipeline de WhatsApp (flujo de un mensaje)

1. WAHA hace `POST /webhook/whatsapp` (evento `message`) → `webhook.py` parsea con
   `parser.parse_webhook`.
2. Se filtra por operador autorizado (`WHATSAPP_OPERATOR_PHONE`).
3. Si es audio/imagen → se descarga el media (`client.get_media_bytes`): WAHA manda
   `payload.media.url` y se baja con un GET autenticado con `X-Api-Key`.
4. Audio → Whisper transcribe. Imagen/texto → Claude extrae el intent.
5. Si el intent requiere confirmación → se guarda como *pending* y se le pregunta
   al operador. La próxima respuesta sí/no resuelve el pending.
6. `dispatcher.dispatch` impacta la BD y se responde por WhatsApp.
7. **Al confirmar una transacción, la sesión se limpia** (`session.clear_session`)
   para no arrastrar contexto entre operaciones.

> WAHA no tiene verificación de webhook tipo Meta (`hub.challenge`); solo `POST`.
> El emparejamiento es por **QR**: se escanea una vez desde el dashboard de WAHA.

## Variables de entorno (WhatsApp)

| Variable | Qué es |
|---|---|
| `WAHA_API_URL` | URL del servidor WAHA (ej. `https://tu-waha.railway.app`) |
| `WAHA_API_KEY` | API key de WAHA (header `X-Api-Key` en cada request) |
| `WAHA_SESSION` | Nombre de la sesión de WAHA (default `default`) |
| `WHATSAPP_OPERATOR_PHONE` | Número del operador autorizado (solo dígitos) |

En el lado de WAHA (su propio servicio/contenedor), conviene setear
`WAHA_DEFAULT_ENGINE=NOWEB` (sin Chromium) y apuntar su webhook a
`…/webhook/whatsapp` con el evento `message`.

Ver `backend/.env.example` para la lista completa (BD, Claude, OpenAI).

## Reglas de negocio clave

- **Cheques** — máquina de estados estricta: `EN_CARTERA` → `VENDIDO` / `FIADO` /
  `COBRADO` / `RECHAZADO`. La cartera web muestra **solo** `EN_CARTERA`.
- **Préstamos** — monedas `ARS`/`USD`; frecuencias diaria/semanal/quincenal/
  mensual/anual; el alta genera el préstamo + sus `cuotas` con fechas calculadas.
- **Movimientos de efectivo** — la cotización la dicta el operador, nunca la IA.
  El dólar blue del navbar (DolarAPI) es decorativo, no afecta cálculos.
- **Reportes** — consolidan ganancias de los tres módulos (spread de cheques +
  intereses de préstamos + spread de divisas), filtrables por día/semana/mes.

## Notificaciones proactivas (recordatorios de cobranza)

> **No implementado todavía.** El job `app/jobs/recordatorios.py` (y `client.send_template`)
> que describían versiones anteriores de esta guía pertenecían al intento de Cloud API,
> que fue revertido — no existen en el código actual.
>
> Con WAHA es más simple: **no hay ventana de 24h ni plantillas aprobadas**, así que un
> job de recordatorios solo necesitaría usar `client.send_text` con texto libre. Si se
> implementa: leer cuotas pendientes que vencen hoy o ya vencieron y mandar un mensaje al
> operador; en Railway, correrlo desde un servicio **Cron** 1×/día.

## Gotchas

- **WAHA es gateway no oficial:** el emparejamiento es por QR (sesión de WhatsApp Web).
  Si la sesión se cae, hay que re-escanear el QR desde el dashboard de WAHA. Usar el
  engine `NOWEB` evita la dependencia de Chromium (la causa de que Evolution no generara
  el QR).
- **El "9" de Argentina:** WAHA puede entregar el `from` sin el 9 intermedio. Si aparece
  "Mensaje de número no autorizado" en los logs, revisar la comparación contra
  `WHATSAPP_OPERATOR_PHONE`.
- **Railway no usa `docker-compose.yml`** — usa `railway.toml` + `backend/Dockerfile`.
  El compose es solo para desarrollo local. WAHA corre como **servicio aparte**.
