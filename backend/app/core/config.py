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
    public_base_url: str = Field(default="")


@lru_cache
def get_settings() -> Settings:
    return Settings()
