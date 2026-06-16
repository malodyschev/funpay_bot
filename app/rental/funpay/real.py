import asyncio
from collections.abc import Callable
from logging import getLogger
from typing import TypeVar

import FunPayAPI
import requests

from app.rental.funpay.interface import FunPayConnector


logger = getLogger(__name__)

T = TypeVar('T')

_RETRIES = 3
_BACKOFF_SECONDS = 2
_REQUESTS_TIMEOUT = 20  # связь с funpay.com бывает нестабильной — даём запас


def build_account(
    golden_key: str,
    user_agent: str | None = None,
    proxy_url: str | None = None,
) -> FunPayAPI.Account:
    """Создать и авторизовать FunPay-аккаунт (синхронно, на старте)."""
    proxy = {'http': proxy_url, 'https': proxy_url} if proxy_url else None
    account = FunPayAPI.Account(
        golden_key,
        user_agent or None,
        requests_timeout=_REQUESTS_TIMEOUT,
        proxy=proxy,
    )
    account.get()  # авторизация (бросит исключение при плохом golden_key)
    logger.info('funpay authorized as %s (id=%s)', account.username, account.id)
    return account


class RealFunPayConnector(FunPayConnector):
    """Боевой коннектор FunPay поверх (синхронной) FunPayAPI.

    Все вызовы библиотеки оборачиваем в to_thread (не блокируем общий
    event-loop) и в ретраи с бэкоффом — funpay.com периодически таймаутит,
    кратковременные сбои переживаем без потери команды.
    """

    def __init__(self, account: FunPayAPI.Account) -> None:
        self._account = account

    async def _call(self, label: str, fn: Callable[..., T], *args: object) -> T:
        last_error: Exception | None = None
        for attempt in range(1, _RETRIES + 1):
            try:
                return await asyncio.to_thread(fn, *args)
            except requests.exceptions.RequestException as exc:
                last_error = exc
                logger.warning(
                    'funpay %s failed (attempt %s/%s): %s', label, attempt, _RETRIES, exc,
                )
                if attempt < _RETRIES:
                    await asyncio.sleep(_BACKOFF_SECONDS * attempt)
        raise last_error  # type: ignore[misc]

    async def send_message(self, chat_id: int, text: str) -> None:
        try:
            await self._call('send_message', self._account.send_message, chat_id, text)
        except requests.exceptions.RequestException:
            raise  # сеть легла (POST не прошёл) — пусть вызывающий знает
        except Exception as exc:
            # POST прошёл, но FunPayAPI не смог разобрать ответ (например, не нашёл
            # div.message-text). Сообщение, скорее всего, доставлено — НЕ ретраим
            # (иначе дубль) и не роняем обработчик.
            logger.warning(
                'send_message: ответ FunPay не распарсился, считаю доставленным: %s', exc,
            )

    async def refund_order(self, order_id: str) -> None:
        await self._call('refund', self._account.refund, order_id)

    async def set_lot_active(self, funpay_lot_id: int, active: bool) -> None:
        def _toggle() -> None:
            fields = self._account.get_lot_fields(funpay_lot_id)
            fields.active = active
            self._account.save_lot(fields)

        await self._call('set_lot_active', _toggle)
        logger.info('funpay lot %s active=%s', funpay_lot_id, active)

    async def get_viewed_lot_id(self, chat_id: int) -> int | None:
        """Лот из панели «Покупатель смотрит» (один GET-запрос chat/?node=).

        Сбой/таймаут или покупатель не на странице лота → None (не роняем !free,
        вызывающий покажет наличие по всем лотам).
        """
        def _fetch() -> str | None:
            chat = self._account.get_chat(chat_id, with_history=False)
            return getattr(chat, 'looking_link', None)

        try:
            link = await asyncio.to_thread(_fetch)
        except Exception as exc:
            logger.warning('get_viewed_lot_id failed for chat %s: %s', chat_id, exc)
            return None
        if not link:
            return None
        tail = link.rstrip('/').rsplit('=', 1)[-1]
        return int(tail) if tail.isdigit() else None
