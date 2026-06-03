from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Sistema de Gestion Financiera y Cartera Privada"
    api_v1_prefix: str = "/api/v1"
<<<<<<< HEAD

    # Base de datos
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/financiera"
    )

    # CORS
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

    # IA
    anthropic_api_key: str = Field(default="")
    openai_api_key: str = Field(default="")

    # Evolution API (WhatsApp)
    evolution_api_url: str = Field(default="http://localhost:8080")
    evolution_api_key: str = Field(default="")
    evolution_instance: str = Field(default="financiera")

    # Número del operador autorizado (sin @s.whatsapp.net, solo dígitos)
    whatsapp_operator_phone: str = Field(default="")

=======
    database_url: str = Field(
        default="postgresql+psycopg://postgres:postgres@localhost:5432/financiera"
    )
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])

>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f

@lru_cache
def get_settings() -> Settings:
    return Settings()
<<<<<<< HEAD
=======

>>>>>>> 3ab33fdda97af856ccedd4601fcc92275968326f
