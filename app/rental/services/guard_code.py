from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.exceptions import SteamModuleError
from app.rental.funpay.events import NewMessageEvent
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.credentials import build_credentials
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class GuardCodeService:
    """W2. Команда !код → выдать текущий Steam Guard код активному арендатору."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)

    async def handle(self, event: NewMessageEvent) -> None:
        """Send the current Guard code to the active renter of this chat."""
        rental = await self.rental_repo.get_active_by_chat(event.chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                event.chat_id,
                'Активная аренда не найдена.',
            )
            return

        account = await self.account_repo.get(rental.account_id)
        try:
            code = await self.deps.steam.generate_code(build_credentials(account))
        except SteamModuleError:
            logger.exception('failed to generate guard code for account %s', account.id)
            await self.deps.funpay.send_message(
                event.chat_id,
                'Не удалось получить код, попробуйте ещё раз через минуту.',
            )
            return

        await self.deps.funpay.send_message(event.chat_id, f'Код Steam Guard: {code}')
