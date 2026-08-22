from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Sistema de Gestion Financiera y Cartera Privada"
    api_v1_prefix: str = "/api/v1"

    # Base de datos
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/financiera"
    )

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalize_db_url(cls, v: str) -> str:
        # Railway inyecta postgresql:// o postgres://; psycopg3 necesita postgresql+psycopg://
        if v.startswith("postgres://"):
            v = "postgresql+psycopg://" + v[len("postgres://"):]
        elif v.startswith("postgresql://"):
            v = "postgresql+psycopg://" + v[len("postgresql://"):]
        return v

    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # IA
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    # ── Motor de IA del bot (ver services/ia/motor.py) ─────────────────────
    # Qué proveedor interpreta cada camino: "anthropic" | "openai". Se eligen
    # por SEPARADO porque son dos trabajos con riesgos distintos: leer una foto
    # de cheque mal es plata mal cargada y no da ninguna señal, mientras que un
    # error interpretando texto se ve en el acto (el bot muestra la operación y
    # el operador la corrige) y además tiene escalada automática.
    # Los dos arrancan en "anthropic" a propósito: un deploy sin tocar env vars
    # no cambia de motor solo, y volver atrás es cambiar una variable.
    ia_provider_texto: str = Field(default="anthropic")
    ia_provider_ocr: str = Field(default="anthropic")
    # Modelos de OpenAI, por env var y no hardcodeados como los de Claude: esto
    # es un motor en evaluación y probar otro modelo tiene que ser cambiar una
    # variable en Railway, no un deploy. Los defaults son el régimen querido, no
    # un mínimo: un deploy sin variables ya rutea como corresponde.
    #
    # "CAPAZ" y no "OCR" (renombrado 2026-08-21): esta ranura es **el modelo más
    # capaz configurado**, y se usa para dos cosas — leer las fotos, si el OCR
    # estuviera en OpenAI, y ser el segundo intento del camino de texto. Se
    # llamaba `OPENAI_MODEL_OCR` y el nombre mentía: con el OCR en Claude (que es
    # como corre hoy) no lee ninguna foto, solo recibe las escaladas del texto.
    openai_model_texto: str = Field(default="gpt-5-mini")
    openai_model_capaz: str = Field(default="gpt-5")
    openai_model_confirmacion: str = Field(default="gpt-5-mini")
    # Esfuerzo de razonamiento ("minimal"|"low"|"medium"|"high"). Vacío = no se
    # manda el parámetro, para poder probar un modelo que no lo soporte.
    openai_effort_texto: str = Field(default="low")
    openai_effort_capaz: str = Field(default="medium")
    # El clasificador de confirmaciones: "minimal" porque decidir si "dale" es
    # un sí no necesita pensarse, y lo que se razone sale del mismo tope que la
    # respuesta (ver `_TOPE_CONFIRMACION` en services/ia/openai_engine.py).
    openai_effort_confirmacion: str = Field(default="minimal")

    # ── Confirmación obligatoria ───────────────────────────────────────────
    # Arriba de estos montos el sistema EXIGE confirmación aunque el modelo no
    # la haya pedido (ver services/whatsapp/confirmacion.py). El prompt tiene la
    # misma regla; esto es la red por debajo, para el día que el modelo la pase
    # por alto y una operación grande entre sin que nadie la vea.
    confirmacion_umbral_ars: float = Field(default=700_000)
    confirmacion_umbral_usd: float = Field(default=500)

    # WAHA (WhatsApp HTTP API — gateway no oficial, engine NOWEB)
    waha_api_url: str = Field(default="http://localhost:3000")
    waha_api_key: str = Field(default="")
    waha_session: str = Field(default="default")

    # Número del operador autorizado (sin @s.whatsapp.net, solo dígitos)
    whatsapp_operator_phone: str = Field(default="")

    # Autenticación (login del panel)
    # Clave para firmar los JWT de sesión (HS256). Obligatoria en producción;
    # el default solo sirve para desarrollo local.
    secret_key: str = Field(default="dev-insecure-secret-change-me")
    # Admin raíz bootstrapeado al arranque (recuperable cambiando la env var).
    admin_username: str = Field(default="admin")
    admin_password: str = Field(default="")

    # URL pública base del sistema, usada para armar el enlace de invitación
    # (p. ej. https://midominio.app). Si queda vacío, el front arma el enlace
    # con su propio origen. Sin barra final.
    # También la usa el chequeo de salud para verificar que WAHA siga apuntando
    # su webhook a este backend (ver services/health.interpretar_webhook).
    public_base_url: str = Field(default="")

    # ── Monitoreo de salud y alertas (ver services/health.py y monitor.py) ──
    # Telegram es el canal de alerta porque NO depende de WhatsApp: cuando se
    # cae la sesión del bot, avisar por WhatsApp es imposible.
    telegram_bot_token: str = Field(default="")
    # Uno o varios chat IDs separados por coma (dueño + soporte, por ejemplo).
    telegram_chat_ids: str = Field(default="")

    # Token que protege GET /health/deep (query ?token= o header X-Health-Token).
    # Vacío = endpoint abierto (solo para desarrollo local).
    health_token: str = Field(default="")

    monitor_activo: bool = Field(default=True)
    monitor_intervalo_segundos: int = Field(default=120)
    # Fallos seguidos antes de alertar: con 2, un timeout transitorio no
    # dispara una alerta que después nadie mira.
    monitor_umbral_fallos: int = Field(default=2)
    # Cada cuánto recordar una caída que sigue abierta.
    monitor_repetir_minutos: int = Field(default=30)
    # Margen tras el deploy antes del primer chequeo (WAHA/Postgres levantando).
    monitor_demora_inicial_segundos: int = Field(default=45)
    # Avisar por Telegram cada vez que el backend arranca. Sirve para detectar
    # reinicios inesperados de Railway (un crash-loop se ve como una tanda), pero
    # en un deploy normal es un mensaje que nadie pidió: apagado por decisión del
    # dueño (2026-08-17), que solo quiere enterarse de caídas y recuperaciones.
    monitor_avisar_arranque: bool = Field(default=False)
    # Si un DEGRADADO merece Telegram. Apagado por la misma decisión: un degradado
    # es una condición que se lee en /health/deep cuando uno quiere mirarla, no
    # algo que justifique interrumpir al dueño. Encenderlo devuelve el aviso único
    # por degradación (nunca el recordatorio periódico, que es solo para caídas).
    monitor_alertar_degradado: bool = Field(default=False)


@lru_cache
def get_settings() -> Settings:
    return Settings()
