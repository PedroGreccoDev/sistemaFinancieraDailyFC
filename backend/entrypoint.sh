#!/bin/sh
set -e

# Si el schema ya existe pero alembic_version no lo registra, estamparlo.
# Esto ocurre cuando la DB fue creada antes de que Alembic la manejara.
python - <<'PYEOF'
import sqlalchemy as sa
from app.core.config import get_settings

engine = sa.create_engine(get_settings().database_url)

with engine.connect() as conn:
    tables = sa.inspect(engine).get_table_names()
    schema_exists   = "clientes" in tables
    version_tracked = False

    if "alembic_version" in tables:
        row = conn.execute(sa.text("SELECT version_num FROM alembic_version")).fetchone()
        version_tracked = row is not None

    if schema_exists and not version_tracked:
        if "alembic_version" not in tables:
            conn.execute(sa.text(
                "CREATE TABLE alembic_version "
                "(version_num VARCHAR(32) NOT NULL, "
                "CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num))"
            ))
        conn.execute(sa.text("INSERT INTO alembic_version (version_num) VALUES ('0001')"))
        conn.commit()
        print("INFO: schema preexistente estampado como revision 0001.")
PYEOF

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
