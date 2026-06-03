FROM python:3.12-slim

# Evitar .pyc y buffering de logs
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias primero (capa de cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código fuente
COPY . .

EXPOSE 8000

# Railway inyecta $PORT; fallback a 8000 para entornos locales.
# La migración corre antes del arranque del servidor para garantizar
# que el schema esté siempre actualizado en cada deploy.
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
