from abc import ABC, abstractmethod


class AdminNotifier(ABC):
    """Интерфейс уведомлений администратора (Telegram)."""

    @abstractmethod
    async def notify(self, text: str) -> None:
        """Отправить администратору информационное уведомление."""

    @abstractmethod
    async def request_refund(self, order_id: str, reason: str) -> None:
        """Запросить у администратора подтверждение возврата по заказу."""
