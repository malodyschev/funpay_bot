import html
from logging import getLogger

from aiogram import Bot

from app.rental.funpay.interface import FunPayConnector


logger = getLogger(__name__)


class TelegramSimFunPayConnector(FunPayConnector):
    """Эмулятор FunPay для ручного теста: всё, что ушло бы покупателю,
    пересылается админу в Telegram. Меняется на реальный коннектор на Stage 2.
    """

    def __init__(self, bot: Bot, admin_ids: list[int]) -> None:
        self._bot = bot
        self._admin_ids = admin_ids

    async def _broadcast(self, text: str) -> None:
        for admin_id in self._admin_ids:
            try:
                await self._bot.send_message(admin_id, text)
            except Exception:
                logger.exception('failed to send sim message to admin %s', admin_id)

    async def send_message(self, chat_id: int, text: str) -> None:
        logger.info('[sim funpay] -> chat %s: %s', chat_id, text)
        body = html.escape(text)
        await self._broadcast(
            f'📨 <b>[чат #{chat_id} → покупателю]</b>\n<blockquote>{body}</blockquote>',
        )

    async def refund_order(self, order_id: str) -> None:
        logger.info('[sim funpay] refund order %s', order_id)
        await self._broadcast(
            f'↩️ <b>[FunPay]</b> возврат по заказу <code>{html.escape(order_id)}</code> '
            f'выполнен (симуляция).',
        )
