import asyncio
import itertools
import re
import threading
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

# Уникальные id для message-событий из LastChatMessageChangedEvent (там id нет).
_msg_counter = itertools.count(1)


async def run_funpay_listener(account: FunPayAPI.Account) -> None:
    """Слушать события FunPay (Runner) и подавать их в наш диспетчер.

    Runner синхронный и блокирующий, поэтому крутим его в отдельном потоке,
    а каждое событие пробрасываем в основной event-loop через
    run_coroutine_threadsafe (обрабатываем по одному, последовательно).

    disable_message_requests=True: НЕ тянем полную историю чата (этот запрос
    у FunPayAPI хрупкий и валится на отдельных чатах) — реагируем на
    LastChatMessageChangedEvent, где есть chat_id, текст и тип последнего
    сообщения. Этого хватает для команд (!код) и отзывов.

    Начиная с FunPayAPI 1.x Runner шлёт запросы не из listen(), а из очереди,
    которую разгребает отдельный воркер Runner.loop(). Без запущенного loop()
    listen() блокируется навсегда (get_result ждёт ответ, которого никто не
    кладёт) — поэтому loop() обязательно крутим во втором демон-потоке.
    """
    loop = asyncio.get_running_loop()

    def worker() -> None:
        runner = Runner(account, disable_message_requests=True)
        threading.Thread(
            target=runner.loop, name='funpay-runner-queue', daemon=True,
        ).start()
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
    elif isinstance(event, events.LastChatMessageChangedEvent):
        await _handle_chat_changed(event.chat)
    elif isinstance(event, events.NewMessageEvent):
        await _handle_message(account, event.message)


async def _handle_order(account: FunPayAPI.Account, order) -> None:
    """Новый оплаченный заказ → находим чат покупателя и отдаём в W1."""
    chat = await asyncio.to_thread(account.get_chat_by_name, order.buyer_username, True)
    if not chat:
        logger.warning('no chat for buyer %s (order %s)', order.buyer_username, order.id)
        return
    amount = getattr(order, 'amount', 1) or 1
    await on_new_order(NewOrderEvent(
        order_id=order.id,
        # При кол-ве > 1 FunPay вшивает «, N шт.» в описание — срезаем, иначе
        # лот не сматчится по названию.
        lot_title=_clean_lot_title(order.description or ''),
        buyer_id=order.buyer_id,
        buyer_username=order.buyer_username,
        chat_id=chat.id,
        amount=amount,
    ))


# Суффикс количества в описании заказа: «, 2 шт.» / «, 1 000 pcs.».
_AMOUNT_SUFFIX = re.compile(r',\s*\d[\d\s]*\s*(?:шт|pcs)\.\s*$')


def _clean_lot_title(description: str) -> str:
    """Убрать хвост «, N шт.» из описания заказа, оставив чистое название лота."""
    return _AMOUNT_SUFFIX.sub('', description).strip()


async def _handle_chat_changed(chat) -> None:
    """Изменилось последнее сообщение чата → команда (!код) или отзыв.

    В режиме без запросов истории нет author_id, поэтому реагируем только на
    распознанные команды. Наши собственные ответы командами не являются —
    диспетчер их игнорирует, цикла не возникает.
    """
    if chat.last_message_type == enums.MessageTypes.NEW_FEEDBACK:
        await on_new_review_by_chat(chat.id)
        return
    if chat.last_message_type not in (enums.MessageTypes.NON_SYSTEM, None):
        return  # прочие системные сообщения (покупка, возврат и т.п.)
    await on_new_message(NewMessageEvent(
        chat_id=chat.id,
        message_id=next(_msg_counter),
        author_id=1,  # author неизвестен; диспетчер фильтрует по тексту команды
        text=chat.last_message_text or '',
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
