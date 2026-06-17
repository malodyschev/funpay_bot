from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class SteamCredentials:
    """Расшифрованные секреты аккаунта для работы со Steam."""

    login: str
    password: str
    shared_secret: str
    identity_secret: str
    steam_id: str | None = None
    device_id: str | None = None


@dataclass
class SteamSessionInfo:
    """Активная сессия Steam-аккаунта (refresh-токен из EnumerateTokens)."""

    description: str           # token_description — браузер/устройство
    last_seen_ts: int | None   # last_seen.time (unix), когда сессия была активна
    country: str | None
    city: str | None


class SteamModule(ABC):
    """Изолированный интерфейс работы со Steam.

    Самая хрупкая часть проекта (Steam меняет auth-флоу) спрятана за
    этим интерфейсом, чтобы при поломке менять одну реализацию.
    """

    @abstractmethod
    async def generate_code(self, credentials: SteamCredentials) -> str:
        """Сгенерировать текущий Steam Guard код (TOTP)."""

    @abstractmethod
    async def login(self, credentials: SteamCredentials) -> None:
        """Залогиниться по maFile-секретам (проверка доступности аккаунта)."""

    @abstractmethod
    async def deauthorize(self, credentials: SteamCredentials) -> int:
        """Деавторизовать все сессии аккаунта (выгнать арендатора в конце аренды).

        Пароль НЕ меняется: арендатор без аутентификатора всё равно не войдёт,
        а коды `!код` мы перестаём выдавать (аренда уже не активна).

        Returns:
            Сколько сессий успешно отозвано.
        """

    @abstractmethod
    async def list_sessions(self, credentials: SteamCredentials) -> list[SteamSessionInfo]:
        """Список активных сессий аккаунта (проверить, вышли ли все/никто не сидит).

        Внимание: сам вызов логинится в Steam, поэтому в списке будет и
        текущая проверочная сессия бота.
        """
