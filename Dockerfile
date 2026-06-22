FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow \
    PYTHONPATH=/app/vendor

# FunPayAPI берём из ./vendor (кастомная сборка), а не с PyPI — см. requirements.txt.

WORKDIR /app

# pg_dump для бэкапов. База python:3.12-slim — Debian 13 (trixie), где штатный
# postgresql-client = 17; pg_dump 17 без проблем дампит сервер Postgres 16
# (клиент новее сервера — это поддерживается).
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Зависимости отдельным слоем — кешируется, пока requirements.txt не менялся.
# Колёса (wheels) для cryptography/lxml/asyncpg есть под 3.12 — компилятор не нужен.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# На старте: накатить alembic-миграции + sync-schema (создаёт недостающие
# таблицы/колонки и сеет дерево категорий, идемпотентно), затем запустить бота.
CMD ["sh", "-c", "alembic upgrade head && python __main__.py sync-schema && python __main__.py run"]
