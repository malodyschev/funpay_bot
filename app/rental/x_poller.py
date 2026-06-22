import asyncio
import html
from logging import getLogger

from aiogram import Bot

from app.database import get_session
from app.rental.admin_bot.keyboards import x_kick_button
from app.rental.services.x_rental import XRentalService
from app.runtime import runtime


logger = getLogger(__name__)

X_POLL_INTERVAL_SECONDS = 120


async def x_expire_once(bot: Bot, admin_ids: list[int]) -> None:
    """Один проход: пометить истёкшие X-аренды (слот освобождается) + алерт админам.

    Деавторизация ручная — бот лишь сообщает, кого выкинуть, с кнопкой «закрыть».
    """
    deps = runtime.get_deps()
    async with get_session() as session:
        alerts = await XRentalService(session, deps).expire_due()

    for rental, account in alerts:
        login = account.login if account else '—'
        buyer = rental.buyer_username or str(rental.buyer_id)
        logged_in = (
            rental.code_requested_at.strftime('%d.%m %H:%M')
            if rental.code_requested_at
            else 'код не запрашивал'
        )
        text = (
            '⏰ <b>Истекла аренда X</b>\n'
            f'Покупатель: {html.escape(buyer)}\n'
            f'Заказ: <code>{html.escape(rental.funpay_order_id)}</code>\n'
            f'Аккаунт: {html.escape(login)}\n'
            f'Вошёл (запросил код): {logged_in}\n'
            'Найди это устройство в session manager X, деавторизуй и нажми кнопку.'
        )
        for admin_id in admin_ids:
            try:
                await bot.send_message(admin_id, text, reply_markup=x_kick_button(rental.id))
            except Exception:
                logger.exception('failed to send x expiry alert to %s', admin_id)
    if alerts:
        logger.info('x poller alerted %s expired rentals', len(alerts))


async def run_x_expiry(bot: Bot, admin_ids: list[int]) -> None:
    """Бесконечный цикл проверки истёкших X-аренд (фоновая задача в run)."""
    logger.info('x expiry poller started (interval=%ss)', X_POLL_INTERVAL_SECONDS)
    while True:
        try:
            await x_expire_once(bot, admin_ids)
        except Exception:
            logger.exception('x expiry iteration failed')
        await asyncio.sleep(X_POLL_INTERVAL_SECONDS)
