import html
from logging import getLogger

from aiogram import Bot

from app.rental.admin_bot.keyboards import refund_request
from app.rental.admin_bot.notifier import AdminNotifier


logger = getLogger(__name__)


class TelegramNotifier(AdminNotifier):
    """Алерты администраторам в Telegram (aiogram). Рассылает всем из списка."""

    def __init__(self, bot: Bot, admin_ids: list[int]) -> None:
        self._bot = bot
        self._admin_ids = admin_ids

    async def _broadcast(self, text: str, reply_markup=None) -> None:
        for admin_id in self._admin_ids:
            try:
                await self._bot.send_message(admin_id, text, reply_markup=reply_markup)
            except Exception:
                logger.exception('failed to send message to admin %s', admin_id)

    async def notify(self, text: str) -> None:
        """Информационный алерт всем админам."""
        await self._broadcast(f'🔔 {html.escape(text)}')

    async def request_refund(self, order_id: str, reason: str) -> None:
        """Запрос подтверждения возврата с инлайн-кнопками Да/Нет."""
        text = (
            f'💸 <b>Запрос возврата</b>\n'
            f'Заказ: <code>{html.escape(order_id)}</code>\n'
            f'Причина: {html.escape(reason)}'
        )
        await self._broadcast(text, reply_markup=refund_request(order_id))
