from __future__ import annotations

import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Permite importar `app` desde el directorio backend/
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.core.config import get_settings  # noqa: E402
from app.db.models import Base  # noqa: E402

# Objeto de configuración de Alembic
alembic_cfg = context.config

# Inyecta la URL real desde Settings (lee DATABASE_URL del entorno)
settings = get_settings()
alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

# Logging estándar de Alembic
if alembic_cfg.config_file_name is not None:
    fileConfig(alembic_cfg.config_file_name)

# Metadata de todos los modelos para autogenerate
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Modo offline: emite SQL sin conexión real a la BD."""
    url = alembic_cfg.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Modo online: aplica migraciones directamente sobre la BD."""
    connectable = engine_from_config(
        alembic_cfg.get_section(alembic_cfg.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
