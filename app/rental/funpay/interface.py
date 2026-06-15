from abc import ABC, abstractmethod


class FunPayConnector(ABC):
    """Изолированный интерфейс работы с FunPay.

    Скрывает неофициальную библиотеку FunPayAPI за абстракцией, чтобы
    при её поломке менять одну реализацию.
    """

    @abstractmethod
    async def send_message(self, chat_id: int, text: str) -> None:
        """Отправить сообщение покупателю в чат."""

    @abstractmethod
    async def refund_order(self, order_id: str) -> None:
        """Вернуть средства по заказу."""
