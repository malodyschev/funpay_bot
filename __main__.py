import asyncio
import getpass
import os
from logging import getLogger
from pathlib import Path

import click

from app.config import get_settings
from app.database import async_engine, get_session
from app.hooks import setup_logging
from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.common.enums import AccountTypeEnum
from app.rental.models import Base
from app.rental.repositories.lot import LotRepository
from app.rental.services.account_loader import AccountLoaderService


logger = getLogger(__name__)


@click.group()
def cli():
    """CLI start point."""


@cli.command()
def init_db():
    """Create all tables (dev only; в проде — alembic)."""
    setup_logging()

    async def _create() -> None:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        await async_engine.dispose()

    asyncio.run(_create())
    logger.info('tables created')


@cli.command('create-lot')
@click.option('--title', required=True, help='Название лота (точно как на FunPay)')
@click.option('--duration', type=int, required=True, help='Длительность аренды, мин.')
@click.option('--game', default=None)
@click.option('--price', type=float, default=None)
@click.option('--template', default=DEFAULT_DELIVERY_TEMPLATE, help='Шаблон выдачи')
def create_lot(title, duration, game, price, template):
    """Создать лот аренды (для теста и боевого пула)."""
    setup_logging()

    async def _create() -> None:
        async with get_session() as session:
            lot = await LotRepository(session).create({
                'title': title,
                'game': game,
                'duration_minutes': duration,
                'price': price,
                'delivery_template': template,
                'active': True,
            })
        click.echo(f'lot created: id={lot.id} "{lot.title}" ({duration} мин.)')

    asyncio.run(_create())


@cli.command('load-account')
@click.option('--mafile', required=True, type=click.Path(exists=True), help='Путь к .maFile')
@click.option('--lot-id', type=int, required=True)
@click.option('--offline', is_flag=True, help='OFFLINE-тип (пароль не трогаем при истечении)')
def load_account(mafile, lot_id, offline):
    """Загрузить Steam-аккаунт в пул из maFile (пароль — интерактивно)."""
    setup_logging()
    password = os.getenv('STEAM_TEST_PASSWORD') or getpass.getpass('Steam password: ')
    raw = Path(mafile).read_text(encoding='utf-8')
    account_type = AccountTypeEnum.OFFLINE if offline else AccountTypeEnum.ONLINE

    async def _load() -> None:
        async with get_session() as session:
            account = await AccountLoaderService(session).load_from_mafile(
                raw_mafile=raw,
                password=password,
                lot_id=lot_id,
                account_type=account_type,
            )
        click.echo(f'account loaded: id={account.id} login={account.login}')

    asyncio.run(_load())


@cli.command('set-password')
@click.option('--id', 'account_id', type=int, required=True, help='id аккаунта в пуле')
def set_password(account_id):
    """Обновить пароль аккаунта (пароль — интерактивно)."""
    setup_logging()
    from app.crypto import encrypt
    from app.rental.repositories.account import AccountRepository

    password = os.getenv('STEAM_TEST_PASSWORD') or getpass.getpass('Новый Steam password: ')

    async def _update() -> None:
        async with get_session() as session:
            await AccountRepository(session).update(
                {'password_enc': encrypt(password)},
                id_=account_id,
            )
        click.echo(f'password updated for account id={account_id}')

    asyncio.run(_update())


@cli.command()
def run():
    """Run the bot (admin panel + scheduler; FunPay эмулируется в Telegram)."""
    setup_logging()
    asyncio.run(_run())


async def _run() -> None:
    from app.rental.admin_bot.bot import build_admin_bot
    from app.rental.admin_bot.sim_connector import TelegramSimFunPayConnector
    from app.rental.admin_bot.telegram_notifier import TelegramNotifier
    from app.rental.poller import run_poller
    from app.rental.steam.real import RealSteamModule
    from app.runtime import RentalDeps, runtime

    settings = get_settings()
    admin_ids = settings.admin_id_list
    if not settings.bot_token or not admin_ids:
        raise click.ClickException('нужны BOT_TOKEN и ADMIN_ID/ADMIN_IDS в .env')

    bot, dp = build_admin_bot(settings.bot_token, admin_ids)
    runtime.deps = RentalDeps(
        funpay=TelegramSimFunPayConnector(bot, admin_ids),
        steam=RealSteamModule(proxy=settings.proxy_url or None),
        notifier=TelegramNotifier(bot, admin_ids),
    )

    poller_task = asyncio.create_task(run_poller())
    logger.info('admin bot started')
    try:
        await dp.start_polling(bot)
    finally:
        poller_task.cancel()
        await bot.session.close()


if __name__ == '__main__':
    cli()
