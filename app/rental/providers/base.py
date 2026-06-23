from abc import ABC, abstractmethod

from app.rental.models.account import Account
from app.rental.models.lot import Lot


class RentalProvider(ABC):
    """Бэкенд аренды по индивидуальному аккаунту (сейчас — Steam).

    Сюда вынесены три операции, в которых логика аренды форкается по провайдеру:
    формирование текста выдачи, генерация кода доступа и деавторизация. Общая
    машинерия (пул аккаунтов, статусы, таймеры, видимость лотов на FunPay) живёт
    в сервисах и от провайдера не зависит. Провайдер выбирается по категории лота
    (см. registry.get_provider + CategoryRepository.resolve).

    Chat (шаренная аренда пула) этот паттерн не использует — он обслуживается
    ChatRentalService напрямую.
    """

    @abstractmethod
    async def build_delivery_text(self, *, lot: Lot, account: Account, minutes: int) -> str:
        """Текст выдачи покупателю при новом заказе (креды + срок по шаблону лота)."""

    @abstractmethod
    async def generate_code(self, account: Account) -> str:
        """Текущий код доступа арендатору (Steam Guard)."""

    @abstractmethod
    async def deauthorize(self, account: Account) -> int:
        """Выгнать арендатора по истечении (сброс сессий). Возвращает число сброшенных."""
