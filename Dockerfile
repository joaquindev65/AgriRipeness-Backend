FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias del sistema necesarias para psycopg y Pillow
RUN apt-get update \
    && apt-get install -y --no-install-recommends libpq-dev gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias Python (capa separada para cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Recolectar archivos estáticos en build time
# Se usa una SECRET_KEY de build que no llega a producción
RUN DJANGO_SECRET_KEY=build-only-not-real \
    DATABASE_URL=sqlite:///tmp/build.db \
    python manage.py collectstatic --noinput

EXPOSE 8000

# Ejecutar migraciones, crear superadmin y arrancar gunicorn
CMD python manage.py migrate --noinput && \
    python manage.py create_superuser_if_missing && \
    gunicorn agriripeness_api.wsgi:application \
        --bind 0.0.0.0:${PORT:-8000} \
        --workers 2 \
        --log-file - \
        --access-logfile -
