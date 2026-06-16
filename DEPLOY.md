# Деплой (Docker Compose)

Сервер: Ubuntu 22.04/24.04, 1 ядро / 1 ГБ / 10 ГБ. Бот + Postgres в контейнерах.

## 1. Подготовка сервера

```bash
# Docker + compose-плагин
curl -fsSL https://get.docker.com | sh

# Swap 1 ГБ (страховка от OOM на 1 ГБ RAM)
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 2. Код и конфиг

```bash
git clone <repo-url> funpay_bot && cd funpay_bot
cp .env.example .env
mkdir -p logs
nano .env
```

Заполни в `.env`:

| Параметр | Что вписать |
|---|---|
| `funpay_golden_key` | golden_key твоего аккаунта FunPay |
| `funpay_user_agent` | User-Agent браузера, с которого залогинен FunPay |
| `proxy_url` | **обязательно для Хельсинки**: RU/резидентный прокси, `http://...` или `socks5://user:pass@host:port` |
| `bot_token` | токен Telegram-бота (@BotFather) |
| `admin_id` | твой Telegram id (несколько — `admin_ids` через запятую) |
| `secret_phrase` | секретная фраза для админки |
| `encryption_key` | сгенерировать (ниже), **больше не менять** |
| `db_password` | задай свой пароль (им же инициализируется Postgres) |
| `log_is_json` | `true` |
| `log_file` | `logs/bot.log` |
| `log_retention_days` | `5` |

Сгенерировать `encryption_key`:
```bash
docker run --rm python:3.12-slim sh -c "pip -q install cryptography && python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
```

> ⚠️ **`encryption_key` нельзя терять/менять.** Им шифруются пароли и секреты Steam-аккаунтов в БД. Сменишь — всё сохранённое перестанет расшифровываться. Сохрани его отдельно (менеджер паролей).

> ⚠️ **`proxy_url` критичен на зарубежном сервере.** Вход в Steam из чужого датацентра без прокси может флагнуть/залочить аккаунты. Прокси используется и для FunPay, и для Steam.

## 3. Запуск

```bash
docker compose up -d --build
docker compose logs -f bot
```

Схема БД накатывается автоматически (`alembic upgrade head` при старте). В логах должно появиться:
`funpay authorized as <ник>` → `funpay listener started` → `rental poller started`.

## 4. Первичная настройка (через Telegram-админку)

После старта зайди в Telegram-бота под админом:
- лоты FunPay подтянутся синком на старте как **черновики** — настрой и включи их в админке;
- заведи Steam-аккаунты в пул, создай лот-продления (см. отдельную инструкцию по продлению).

Разовые CLI-команды (если нужны) — через контейнер:
```bash
# обновить текст выдачи у всех лотов
docker compose exec bot python __main__.py reset-templates --yes

# загрузить Steam-аккаунт из maFile (спросит пароль)
docker compose cp ./acc.maFile bot:/tmp/acc.maFile
docker compose exec bot python __main__.py load-account --mafile /tmp/acc.maFile --lot-id <id>
```

## 5. Обслуживание

```bash
# обновить бота после изменений в коде
git pull && docker compose up -d --build

# перезапуск / остановка
docker compose restart bot
docker compose down

# бэкап БД
docker compose exec postgres pg_dump -U postgres funpay_bot > backup_$(date +%F).sql

# логи: stdout — docker compose logs; файл с ротацией 5 дней — ./logs/bot.log
```

## Заметки

- БД (порт 5437) проброшена только на `127.0.0.1` — снаружи недоступна.
- `restart: unless-stopped` — бот и Postgres сами поднимутся после перезагрузки сервера.
- Данные Postgres — в volume `funpay_bot_pgdata` (переживают пересборку контейнера).
