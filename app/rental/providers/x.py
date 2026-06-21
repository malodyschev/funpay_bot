from app.rental.common.exceptions import ProviderNotReadyError
from app.rental.models.account import Account
from app.rental.models.lot import Lot
from app.rental.providers.base import RentalProvider


_NOT_READY = (
    'Провайдер X ещё не подключён: логика выдачи/кода с почты/деавторизации '
    'будет добавлена на Этапе 2.'
)


class XProvider(RentalProvider):
    """Заглушка под личное приложение X.

    Каркас уже есть (категория с provider=x), но логика выдачи — код с почты и
    свой механизм деавторизации — реализуется на Этапе 2. До тех пор любой вызов
    бьёт понятной ошибкой, чтобы заказ по X не «провалился молча».
    """

    async def build_delivery_text(self, *, lot: Lot, account: Account, minutes: int) -> str:
        raise ProviderNotReadyError(_NOT_READY)

    async def generate_code(self, account: Account) -> str:
        raise ProviderNotReadyError(_NOT_READY)

    async def deauthorize(self, account: Account) -> int:
        raise ProviderNotReadyError(_NOT_READY)
