FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    TZ=Europe/Moscow

WORKDIR /app

# Зависимости отдельным слоем — кешируется, пока requirements.txt не менялся.
# Колёса (wheels) для cryptography/lxml/asyncpg есть под 3.12 — компилятор не нужен.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# На старте: накатить миграции (идемпотентно) и запустить бота.
CMD ["sh", "-c", "alembic upgrade head && python __main__.py run"]
