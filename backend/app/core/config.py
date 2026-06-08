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

    # WhatsApp Cloud API (Meta oficial)
    # Token permanente del System User (Meta Business). NO el token temporal de 24h.
    whatsapp_access_token: str = Field(default="")
    # ID del número emisor (Phone Number ID, no el número en sí).
    whatsapp_phone_number_id: str = Field(default="")
    # Token que elegís vos; Meta lo usa para verificar el webhook (GET).
    whatsapp_verify_token: str = Field(default="")
    # App Secret de la app de Meta. Si está seteado, se valida la firma del webhook.
    whatsapp_app_secret: str = Field(default="")
    # Versión de la Graph API.
    whatsapp_api_version: str = Field(default="v21.0")

    # Número del operador autorizado (solo dígitos, con código de país)
    whatsapp_operator_phone: str = Field(default="")

    # Plantilla aprobada para los recordatorios de cobranza (job proactivo).
    # El nombre y el idioma deben coincidir con la plantilla creada en Meta.
    whatsapp_recordatorio_template: str = Field(default="recordatorio_cuota")
    whatsapp_template_lang: str = Field(default="es_AR")


@lru_cache
def get_settings() -> Settings:
    return Settings()
