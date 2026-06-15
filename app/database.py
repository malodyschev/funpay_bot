from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.engine.url import URL
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings


settings = get_settings()


def get_database_url() -> URL | str:
    """Вернуть URL БД: если задан db_url (sqlite для тестов/дева) — берём его,
    иначе собираем строку подключения к Postgres из db_* настроек.
    """
    if settings.db_url:
        return settings.db_url
    return URL.create(
        drivername='postgresql+asyncpg',
        username=settings.db_username,
        password=settings.db_password,
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )


async_engine = create_async_engine(
    get_database_url(),
    echo=settings.db_echo,
    pool_pre_ping=True,
)

async_session = async_sessionmaker(async_engine, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Открыть сессию БД как контекст-менеджер (закроется автоматически)."""
    async with async_session() as session:
        yield session
