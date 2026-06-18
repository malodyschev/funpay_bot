FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow \
    PYTHONPATH=/app/vendor

# FunPayAPI берём из ./vendor (кастомная сборка), а не с PyPI — см. requirements.txt.

WORKDIR /app

# pg_dump 16 для бэкапов (в стандартном debian — только 15, он откажется
# дампить сервер 16). Ставим клиент из официального PGDG-репозитория.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
       | gpg --dearmor -o /usr/share/keyrings/pgdg.gpg \
    && echo 'deb [signed-by=/usr/share/keyrings/pgdg.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main' \
       > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-16 \
    && rm -rf /var/lib/apt/lists/*

# Зависимости отдельным слоем — кешируется, пока requirements.txt не менялся.
# Колёса (wheels) для cryptography/lxml/asyncpg есть под 3.12 — компилятор не нужен.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# На старте: накатить миграции (идемпотентно) и запустить бота.
CMD ["sh", "-c", "alembic upgrade head && python __main__.py run"]
