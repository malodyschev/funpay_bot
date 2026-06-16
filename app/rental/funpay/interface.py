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

    @abstractmethod
    async def set_lot_active(self, funpay_lot_id: int, active: bool) -> None:
        """Показать/скрыть лот на FunPay (авто-скрытие при продаже)."""

    @abstractmethod
    async def get_viewed_lot_id(self, chat_id: int) -> int | None:
        """ID оффера FunPay, который покупатель сейчас смотрит (для !free до покупки).

        None, если покупатель не на странице лота или данные недоступны —
        тогда !free показывает наличие по всем лотам.
        """
