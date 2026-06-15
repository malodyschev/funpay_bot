from logging import getLogger

from app.rental.admin_bot.notifier import AdminNotifier


logger = getLogger(__name__)


class ConsoleNotifier(AdminNotifier):
    """Заглушка нотификатора: пишет в лог вместо Telegram."""

    async def notify(self, text: str) -> None:
        logger.warning('[admin] %s', text)

    async def request_refund(self, order_id: str, reason: str) -> None:
        logger.warning('[admin] требуется подтверждение возврата заказа %s (%s)', order_id, reason)
