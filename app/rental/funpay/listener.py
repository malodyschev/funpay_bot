import asyncio
from logging import getLogger

import FunPayAPI
from FunPayAPI import Runner, enums, events

from app.config import get_settings
from app.rental.funpay.events import NewMessageEvent, NewOrderEvent
from app.rental.services.dispatcher import (
    on_new_message,
    on_new_order,
    on_new_review_by_chat,
)


logger = getLogger(__name__)
settings = get_settings()


async def run_funpay_listener(account: FunPayAPI.Account) -> None:
    """Слушать события FunPay (Runner) и подавать их в наш диспетчер.

    Runner синхронный и блокирующий, поэтому крутим его в отдельном потоке,
    а каждое событие пробрасываем в основной event-loop через
    run_coroutine_threadsafe (обрабатываем по одному, последовательно).
    """
    loop = asyncio.get_running_loop()

    def worker() -> None:
        runner = Runner(account)
        for event in runner.listen(requests_delay=settings.funpay_requests_delay):
            try:
                asyncio.run_coroutine_threadsafe(_handle(account, event), loop).result()
            except Exception:
                logger.exception('funpay event handling failed')

    logger.info('funpay listener started')
    await asyncio.to_thread(worker)


async def _handle(account: FunPayAPI.Account, event) -> None:
    if isinstance(event, events.NewOrderEvent):
        await _handle_order(account, event.order)
    elif isinstance(event, events.NewMessageEvent):
        await _handle_message(account, event.message)


async def _handle_order(account: FunPayAPI.Account, order) -> None:
    """Новый оплаченный заказ → находим чат покупателя и отдаём в W1."""
    chat = await asyncio.to_thread(account.get_chat_by_name, order.buyer_username, True)
    if not chat:
        logger.warning('no chat for buyer %s (order %s)', order.buyer_username, order.id)
        return
    await on_new_order(NewOrderEvent(
        order_id=order.id,
        lot_title=order.description or '',
        buyer_id=order.buyer_id,
        buyer_username=order.buyer_username,
        chat_id=chat.id,
    ))


async def _handle_message(account: FunPayAPI.Account, message) -> None:
    """Сообщение в чате: отзыв → продление, обычное → команды (!код и т.д.)."""
    if message.type == enums.MessageTypes.NEW_FEEDBACK:
        await on_new_review_by_chat(message.chat_id)
        return
    if message.type != enums.MessageTypes.NON_SYSTEM:
        return  # прочие системные сообщения игнорируем
    if message.by_bot or message.author_id == account.id:
        return  # это наши собственные сообщения
    await on_new_message(NewMessageEvent(
        chat_id=message.chat_id,
        message_id=message.id,
        author_id=message.author_id,
        text=message.text or '',
    ))
