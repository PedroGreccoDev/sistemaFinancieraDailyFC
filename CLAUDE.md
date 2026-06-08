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
- **WhatsApp:** **WhatsApp Cloud API oficial de Meta** (webhook directo a FastAPI).
- **IA visión/razonamiento:** Claude (Anthropic) — `app/services/ia/claude.py`.
- **IA transcripción de audio:** Whisper (OpenAI) — `app/services/ia/whisper.py`.

> Nota histórica: antes se usaba Evolution API (gateway no oficial). Se migró a la
> Cloud API oficial por estabilidad y para evitar bans de Meta.

## Estructura

```
backend/app/
  main.py                  # FastAPI app, routers, healthcheck, SPA fallback
  core/config.py           # Settings (pydantic-settings, lee .env / env de Railway)
  api/routes/              # Endpoints REST + webhook de WhatsApp
    webhook.py             # GET (verificación Meta) + POST (mensajes entrantes)
  services/
    whatsapp/
      client.py            # Envío de texto y descarga de media (Cloud API)
      parser.py            # Normaliza el payload del webhook -> IncomingMessage
      dispatcher.py        # Aplica el intent extraído sobre la BD
      session.py           # Historial corto en memoria + pending intents
    ia/claude.py           # Extracción de intención (texto/imagen + historial)
    ia/whisper.py          # Transcripción de notas de voz
    cheques.py / prestamos.py / movimientos.py / clientes.py / reportes.py
  jobs/
    recordatorios.py       # Job proactivo: recordatorios de cobranza (cron)
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

1. Meta hace `POST /webhook/whatsapp` → `webhook.py` valida firma HMAC (si hay
   `WHATSAPP_APP_SECRET`) y parsea con `parser.parse_webhook`.
2. Se filtra por operador autorizado (`WHATSAPP_OPERATOR_PHONE`).
3. Si es audio/imagen → se descarga el media (`client.get_media_bytes`, 2 pasos).
4. Audio → Whisper transcribe. Imagen/texto → Claude extrae el intent.
5. Si el intent requiere confirmación → se guarda como *pending* y se le pregunta
   al operador. La próxima respuesta sí/no resuelve el pending.
6. `dispatcher.dispatch` impacta la BD y se responde por WhatsApp.
7. **Al confirmar una transacción, la sesión se limpia** (`session.clear_session`)
   para no arrastrar contexto entre operaciones.

### Verificación del webhook (Meta)
`GET /webhook/whatsapp` responde el `hub.challenge` si `hub.verify_token` coincide
con `WHATSAPP_VERIFY_TOKEN`. Está registrado en el router **antes** del catch-all
del SPA en `main.py`, por eso tiene prioridad.

## Variables de entorno (WhatsApp)

| Variable | Qué es |
|---|---|
| `WHATSAPP_ACCESS_TOKEN` | Token permanente del System User de Meta |
| `WHATSAPP_PHONE_NUMBER_ID` | ID del número emisor (no el número en sí) |
| `WHATSAPP_VERIFY_TOKEN` | String propio para verificar el webhook |
| `WHATSAPP_APP_SECRET` | App Secret de Meta (valida firma del webhook) |
| `WHATSAPP_API_VERSION` | Versión de la Graph API (default `v21.0`) |
| `WHATSAPP_OPERATOR_PHONE` | Número del operador autorizado (solo dígitos) |

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

`app/jobs/recordatorios.py` manda al operador un mensaje por cada cuota pendiente
que vence hoy o ya venció. Como el bot escribe primero (posiblemente fuera de la
ventana de 24h), usa una **plantilla aprobada de Meta** vía `client.send_template`,
no texto libre.

- Correr a mano / cron: `python -m app.jobs.recordatorios`
- En Railway: crear un servicio **Cron** que ejecute ese comando 1×/día.
- La plantilla (`WHATSAPP_RECORDATORIO_TEMPLATE`, default `recordatorio_cuota`) debe
  estar aprobada en Meta con 4 placeholders en el cuerpo, ej.:
  `📅 Cobranza: cuota {{1}} de {{2}} por {{3}} (vence {{4}}).`
  El idioma (`WHATSAPP_TEMPLATE_LANG`, default `es_AR`) debe coincidir exacto.

> La **auto-cancelación de préstamos** (cuando se cobra la última cuota, el préstamo
> pasa a `CANCELADO`) NO usa plantilla: el aviso va en la respuesta al mensaje del
> operador, siempre dentro de la ventana de 24h. Ver `dispatcher.py` / `prestamos.py`.

## Gotchas

- **Ventana de 24h (Cloud API):** solo se puede mandar texto libre dentro de las
  24h del último mensaje del operador. Para escribir primero (fuera de ventana) hay
  que usar plantillas aprobadas (`send_template`); si no, falla con error `131047`.
- **El "9" de Argentina:** Meta a veces entrega el `from` sin el 9 intermedio. Si
  aparece "Mensaje de número no autorizado" en los logs, revisar la comparación
  contra `WHATSAPP_OPERATOR_PHONE`.
- **Railway no usa `docker-compose.yml`** — usa `railway.toml` + `backend/Dockerfile`.
  El compose es solo para desarrollo local.
