from logging import getLogger

from app.rental.steam.interface import SteamCredentials, SteamModule, SteamSessionInfo


logger = getLogger(__name__)


class FakeSteamModule(SteamModule):
    """Заглушка Steam для разработки и тестов (без реального Steam)."""

    def __init__(self) -> None:
        self.sessions: list[SteamSessionInfo] = []  # что вернёт list_sessions в тестах

    async def generate_code(self, credentials: SteamCredentials) -> str:
        logger.info('[fake steam] generate_code for %s', credentials.login)
        return 'ABCDE'

    async def login(self, credentials: SteamCredentials) -> None:
        logger.info('[fake steam] login %s', credentials.login)

    async def deauthorize(self, credentials: SteamCredentials) -> int:
        logger.info('[fake steam] deauthorize for %s', credentials.login)
        return 1

    async def list_sessions(self, credentials: SteamCredentials) -> list[SteamSessionInfo]:
        logger.info('[fake steam] list_sessions for %s', credentials.login)
        return self.sessions
