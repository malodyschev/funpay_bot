from logging import getLogger

from app.rental.steam.interface import SteamCredentials, SteamModule


logger = getLogger(__name__)


class FakeSteamModule(SteamModule):
    """Заглушка Steam для разработки и тестов (без реального Steam)."""

    async def generate_code(self, credentials: SteamCredentials) -> str:
        logger.info('[fake steam] generate_code for %s', credentials.login)
        return 'ABCDE'

    async def login(self, credentials: SteamCredentials) -> None:
        logger.info('[fake steam] login %s', credentials.login)

    async def deauthorize(self, credentials: SteamCredentials) -> int:
        logger.info('[fake steam] deauthorize for %s', credentials.login)
        return 1
