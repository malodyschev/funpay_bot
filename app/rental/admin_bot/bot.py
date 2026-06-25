import contextlib
from logging import getLogger

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import ErrorEvent, TelegramObject

from app.rental.admin_bot.handlers import (
    accounts,
    bind,
    blacklist,
    chat_accounts,
    manage,
    menu,
    refund,
)


logger = getLogger(__name__)


class IsAdmin(BaseFilter):
    """Пропускает только апдейты от админов из списка."""

    def __init__(self, admin_ids: list[int]) -> None:
        self.admin_ids = set(admin_ids)

    async def __call__(self, event: TelegramObject) -> bool:
        user = getattr(event, 'from_user', None)
        return bool(user and user.id in self.admin_ids)


def build_admin_bot(token: str, admin_ids: list[int]) -> tuple[Bot, Dispatcher]:
    """Собрать Bot + Dispatcher админки (HTML, FSM в памяти, фильтр админов)."""
    bot = Bot(token=token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    admin_only = IsAdmin(admin_ids)
    dp.message.filter(admin_only)
    dp.callback_query.filter(admin_only)

    routers = (
        menu.router,
        accounts.router,
        manage.router,
        bind.router,
        refund.router,
        chat_accounts.router,
        blacklist.router,
    )
    for router in routers:
        dp.include_router(router)

    dp.errors.register(_on_error)
    return bot, dp


async def _on_error(event: ErrorEvent) -> bool:
    """Глобально гасим callback при любой ошибке, чтобы кнопка не висела."""
    exc = event.exception
    callback = event.update.callback_query
    if isinstance(exc, TelegramBadRequest) and 'message is not modified' in str(exc):
        if callback:
            await callback.answer()
        return True
    logger.error('admin bot handler error', exc_info=exc)
    if callback:
        with contextlib.suppress(TelegramBadRequest):
            await callback.answer('Ошибка — см. логи', show_alert=True)
    return True
