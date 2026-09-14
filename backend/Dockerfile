FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY backend/pyproject.toml /app/backend/pyproject.toml
COPY backend/src /app/backend/src
RUN pip install --upgrade pip && pip install /app/backend

COPY backend/alembic.ini /app/alembic.ini
COPY backend/migrations /app/migrations
COPY database/seed /app/database/seed

RUN useradd --create-home --uid 10001 dashboard && chown -R dashboard:dashboard /app
USER dashboard

EXPOSE 8000
CMD ["veriseq-api"]

