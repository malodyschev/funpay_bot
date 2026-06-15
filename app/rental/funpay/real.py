import asyncio
from logging import getLogger

import FunPayAPI

from app.rental.funpay.interface import FunPayConnector


logger = getLogger(__name__)


def build_account(
    golden_key: str,
    user_agent: str | None = None,
    proxy_url: str | None = None,
) -> FunPayAPI.Account:
    """Создать и авторизовать FunPay-аккаунт (синхронно, на старте)."""
    proxy = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
    account = FunPayAPI.Account(golden_key, user_agent or None, proxy=proxy)
    account.get()  # авторизация (бросит исключение при плохом golden_key)
    logger.info('funpay authorized as %s (id=%s)', account.username, account.id)
    return account


class RealFunPayConnector(FunPayConnector):
    """Боевой коннектор FunPay поверх (синхронной) FunPayAPI.

    Все вызовы библиотеки оборачиваем в to_thread, чтобы не блокировать
    общий event-loop (там же крутятся админ-бот и поллер).
    """

    def __init__(self, account: FunPayAPI.Account) -> None:
        self._account = account

    async def send_message(self, chat_id: int, text: str) -> None:
        await asyncio.to_thread(self._account.send_message, chat_id, text)

    async def refund_order(self, order_id: str) -> None:
        await asyncio.to_thread(self._account.refund, order_id)
