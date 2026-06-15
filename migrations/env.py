import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import get_database_url
from app.rental.models import Base
from app.rental.models.type_decorators import EnumAsString


config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def render_item(type_, obj, autogen_context):
    """Render EnumAsString columns as plain String in migrations.

    Чтобы миграции не зависели от прикладного кода — в БД это просто VARCHAR.
    """
    if type_ == 'type' and isinstance(obj, EnumAsString):
        return 'sa.String(length=32)'
    return False


def do_run_migrations(connection) -> None:
    """Configure context and run migrations."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        render_as_batch=True,
        render_item=render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Run migrations in 'online' mode with an async engine."""
    engine = create_async_engine(get_database_url())
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


asyncio.run(run_migrations_online())