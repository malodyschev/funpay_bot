from logging import getLogger

from app.rental.steam.deauth import deauthorize_all_sessions, list_account_sessions
from app.rental.steam.interface import SteamCredentials, SteamModule, SteamSessionInfo
from app.rental.steam.login import login_to_steam
from app.rental.steam.totp import generate_steam_code


logger = getLogger(__name__)


class RealSteamModule(SteamModule):
    """Боевая реализация работы со Steam (всё проверено на живом аккаунте).

    `generate_code` — чистый TOTP из shared_secret (без сети).
    `login` — полный новый auth-флоу Steam (логин+пароль+TOTP → web-сессия).
    `deauthorize` — отзыв всех сессий аккаунта (EnumerateTokens +
    RevokeRefreshToken с подписью shared_secret) — выгоняет арендатора.
    """

    def __init__(self, proxy: str | None = None) -> None:
        """proxy — опциональный прокси для всех запросов к Steam."""
        self._proxy = proxy

    async def generate_code(self, credentials: SteamCredentials) -> str:
        """Сгенерировать текущий Steam Guard код (TOTP из shared_secret)."""
        return generate_steam_code(credentials.shared_secret)

    async def login(self, credentials: SteamCredentials) -> None:
        """Проверить доступность аккаунта: залогиниться и сразу закрыть сессию."""
        session = await login_to_steam(credentials, proxy=self._proxy)
        await session.close()

    async def deauthorize(self, credentials: SteamCredentials) -> int:
        """Залогиниться и отозвать все сессии аккаунта (выгнать арендатора)."""
        session = await login_to_steam(credentials, proxy=self._proxy)
        try:
            return await deauthorize_all_sessions(session, credentials.shared_secret)
        finally:
            await session.close()

    async def list_sessions(self, credentials: SteamCredentials) -> list[SteamSessionInfo]:
        """Залогиниться и вернуть список активных сессий (для проверки в админке)."""
        session = await login_to_steam(credentials, proxy=self._proxy)
        try:
            return await list_account_sessions(session)
        finally:
            await session.close()
