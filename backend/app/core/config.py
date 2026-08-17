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
