from enum import StrEnum, unique


@unique
class AccountStatusEnum(StrEnum):
    """Статус Steam-аккаунта в пуле.

    FREE — свободен, можно выдавать; RENTED — сейчас в аренде;
    DEAUTHORIZING — идёт деавторизация сессий по истечении; OFFLINE — выведен
    из ротации; BANNED — забанен Steam; ERROR — нужен ручной разбор.
    """

    FREE = 'free'
    RENTED = 'rented'
    DEAUTHORIZING = 'deauthorizing'
    OFFLINE = 'offline'
    BANNED = 'banned'
    ERROR = 'error'

    @classmethod
    def available_for_rent(cls) -> list['AccountStatusEnum']:
        """Статусы, из которых аккаунт можно взять под новую аренду."""
        return [cls.FREE]


@unique
class AccountTypeEnum(StrEnum):
    """Тип аккаунта — определяет поведение в конце аренды."""

    ONLINE = 'online'  # сессии деавторизуются по истечении (выгоняем арендатора)
    OFFLINE = 'offline'  # просто возвращаем в пул


@unique
class RentalStatusEnum(StrEnum):
    """Статус аренды по жизненному циклу.

    ACTIVE — идёт; EXPIRING — захвачена поллером, идёт обработка истечения;
    EXPIRED — истекла (аккаунт возвращён); COMPLETED — закрыта штатно;
    REFUNDED — оформлен возврат; ERROR — сбой обработки.
    """

    ACTIVE = 'active'
    EXPIRING = 'expiring'
    EXPIRED = 'expired'
    COMPLETED = 'completed'
    REFUNDED = 'refunded'
    ERROR = 'error'


@unique
class FulfillmentEnum(StrEnum):
    """Тип выдачи категории — определяет, какой логикой обрабатывается заказ.

    RENTAL — аренда (пул аккаунтов + жизненный цикл); AUTODELIVERY — автовыдача
    (выдачей занимается сам FunPay, бот не вмешивается); OTHER — прочее/услуги
    (ручная обработка). Хранится на ветке дерева категорий, лист наследует.
    """

    RENTAL = 'rental'
    AUTODELIVERY = 'autodelivery'
    OTHER = 'other'


@unique
class ProviderEnum(StrEnum):
    """Провайдер аренды — выбирает бэкенд выдачи/деавторизации (драйвер логики).

    STEAM — Steam-аккаунты (maFile, Guard-коды, деавторизация сессий); X — личное
    приложение (код с почты, своя деавторизация). Новые игры внутри провайдера —
    это данные (подкатегории), новый провайдер — это новый код.
    """

    STEAM = 'steam'
    X = 'x'


@unique
class XRentalStatusEnum(StrEnum):
    """Статус аренды X (мультитенант: несколько аренд на одном аккаунте).

    ACTIVE — идёт, занимает слот, код выдаётся; EXPIRED — срок вышел (слот сразу
    освобождён, код не выдаём, админу алерт «кикни»); CLOSED — админ подтвердил
    кик / закрыто вручную.
    """

    ACTIVE = 'active'
    EXPIRED = 'expired'
    CLOSED = 'closed'


@unique
class ExtensionReasonEnum(StrEnum):
    """Причина продления аренды (за отзыв, вручную админом или покупкой лота)."""

    REVIEW = 'review'
    MANUAL = 'manual'
    PURCHASE = 'purchase'
