from app.rental.models.bot_state import BotState
from app.rental.repositories.base import Repository


class BotStateRepository(Repository[BotState]):
    model = BotState

    async def get_value(self, key: str) -> str | None:
        """Прочитать значение по ключу из служебного хранилища состояния бота."""
        state = await self.get_or_none(key=key)
        return state.value if state else None

    async def set_value(self, key: str, value: str) -> None:
        """Записать значение по ключу (создать или обновить)."""
        state = await self.get_or_none(key=key)
        if state:
            await self.update({'value': value}, key=key)
        else:
            await self.create({'key': key, 'value': value})
