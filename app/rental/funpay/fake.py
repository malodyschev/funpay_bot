from logging import getLogger

from app.rental.funpay.interface import FunPayConnector


logger = getLogger(__name__)


class FakeFunPayConnector(FunPayConnector):
    """Заглушка FunPay для разработки и тестов."""

    def __init__(self) -> None:
        self.sent: list[tuple[int, str]] = []
        self.refunded: list[str] = []
        self.lot_active: list[tuple[int, bool]] = []
        self.viewed_lot_id: int | None = None  # для тестов !free до покупки

    async def send_message(self, chat_id: int, text: str) -> None:
        logger.info('[fake funpay] -> chat %s: %s', chat_id, text)
        self.sent.append((chat_id, text))

    async def refund_order(self, order_id: str) -> None:
        logger.info('[fake funpay] refund order %s', order_id)
        self.refunded.append(order_id)

    async def set_lot_active(self, funpay_lot_id: int, active: bool) -> None:
        logger.info('[fake funpay] lot %s active=%s', funpay_lot_id, active)
        self.lot_active.append((funpay_lot_id, active))

    async def get_viewed_lot_id(self, chat_id: int) -> int | None:
        return self.viewed_lot_id
