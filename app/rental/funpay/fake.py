from logging import getLogger

from app.rental.funpay.interface import FunPayConnector


logger = getLogger(__name__)


class FakeFunPayConnector(FunPayConnector):
    """Заглушка FunPay для разработки и тестов."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.refunded: list[str] = []

    async def send_message(self, chat_id: int, text: str) -> None:
        logger.info('[fake funpay] -> chat %s: %s', chat_id, text)
        self.sent.append((chat_id, text))

    async def refund_order(self, order_id: str) -> None:
        logger.info('[fake funpay] refund order %s', order_id)
        self.refunded.append(order_id)
