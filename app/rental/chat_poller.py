import asyncio
import html
from logging import getLogger

from aiogram import Bot

from app.database import get_session
from app.rental.admin_bot.keyboards import chat_kick_button
from app.rental.common.code_log import parse_code_times
from app.rental.services.chat_rental import ChatRentalService
from app.runtime import runtime


logger = getLogger(__name__)

CHAT_POLL_INTERVAL_SECONDS = 120


async def chat_expire_once(bot: Bot, admin_ids: list[int]) -> None:
    """Один проход: пометить истёкшие Chat-аренды (слот освобождается) + алерт админам.

    Деавторизация ручная — бот лишь сообщает, кого выкинуть, с кнопкой «закрыть».
    """
    deps = runtime.get_deps()
    # Сначала предупреждаем покупателей за ~час до конца, потом истекаем просроченные.
    async with get_session() as session:
        await ChatRentalService(session, deps).warn_due()
    async with get_session() as session:
        alerts = await ChatRentalService(session, deps).expire_due()

    for rental, account in alerts:
        login = account.login if account else '—'
        buyer = rental.buyer_username or str(rental.buyer_id)
        # Когда арендатор входил (= запрашивал код) — якорь для поиска устройств
        # в session manager. Показываем ВСЕ входы по порядку, сколько бы их ни было.
        times = parse_code_times(rental.code_log)
        if not times:
            login_block = 'Код входа: не запрашивал (возможно, не заходил)\n'
        else:
            entries = '\n'.join(
                f'  {i}. {when:%d.%m %H:%M}' for i, when in enumerate(times, 1)
            )
            login_block = f'Входы (запросы кода), всего {len(times)}:\n{entries}\n'
        text = (
            '⏰ <b>Истекла аренда Chat</b>\n'
            f'Покупатель: {html.escape(buyer)}\n'
            f'Заказ: <code>{html.escape(rental.funpay_order_id)}</code>\n'
            f'Аккаунт: {html.escape(login)}\n'
            f'{login_block}'
            'Найди это устройство в session manager Chat, деавторизуй и нажми кнопку.'
        )
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=chat_kick_button(rental.id))
            except Exception:
                logger.exception('failed to send chat expiry alert to %s', admin_id)
    if alerts:
        logger.info('chat poller alerted %s expired rentals', len(alerts))


async def run_chat_expiry(bot: Bot, admin_ids: list[int]) -> None:
    """Бесконечный цикл проверки истёкших Chat-аренд (фоновая задача в run)."""
    logger.info('chat expiry poller started (interval=%ss)', CHAT_POLL_INTERVAL_SECONDS)
    while True:
        try:
            await chat_expire_once(bot, admin_ids)
        except Exception:
            logger.exception('chat expiry iteration failed')
        await asyncio.sleep(CHAT_POLL_INTERVAL_SECONDS)
