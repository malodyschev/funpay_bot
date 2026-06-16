import os
import pathlib
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Все настройки приложения (читаются из .env и переменных окружения)."""

    env: str = 'local'
    version: str = '0.1.0'
    log_is_json: bool = False
    log_level: int = 20
    log_file: str = ''  # путь к файлу логов; пусто = только stdout (без ротации в файл)
    log_retention_days: int = 5  # сколько дней хранить ротируемые файлы логов

    db_url: str = ''  # переопределяет сборку URL ниже (напр. sqlite+aiosqlite:///./dev.db)
    db_name: str = ''
    db_username: str = ''
    db_password: str = ''
    db_host: str = 'localhost'
    db_port: int = 5432
    db_echo: bool = False

    funpay_golden_key: str = ''
    funpay_user_agent: str = ''
    funpay_requests_delay: int = 4
    proxy_url: str = ''

    bot_token: str = ''
    admin_id: str = ''  # один или несколько TG id через запятую: "123" или "123,456"
    admin_ids: str = ''  # синоним admin_id (тоже через запятую)
    secret_phrase: str = ''

    encryption_key: str = ''

    hours_for_review: int = 1
    warn_before_minutes: int = 10
    deauthorize_retries: int = 3

    model_config = SettingsConfigDict(
        env_file=os.getenv('ENV_FILE', '.env'),
        extra='ignore',
    )

    @property
    def admin_id_list(self) -> list[int]:
        """Список TG id админов (admin_id и admin_ids, через запятую), без дублей."""
        ids: list[int] = []
        for raw in (self.admin_id, self.admin_ids):
            for part in raw.replace(' ', '').split(','):
                if part:
                    ids.append(int(part))
        return list(dict.fromkeys(ids))


@lru_cache
def get_settings(env_file_path: str | None = None) -> Settings:
    """Вернуть настройки (кэшируется через lru_cache — читаем .env один раз)."""
    if not env_file_path:
        execution_directory = pathlib.Path(__file__).parent.parent.resolve()
        env_file_path = str(execution_directory / '.env')
    return Settings(_env_file=env_file_path, _env_file_encoding='utf-8')
