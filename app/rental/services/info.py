import math
from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.commands import FAQ_TEXT
from app.rental.common.enums import RentalStatusEnum
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class InfoService:
    """W6. Сервисные команды покупателя: !время, !наличие, !помощь."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)

    async def time_left(self, chat_id: int) -> None:
        """Tell the renter how much time is left."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(chat_id, 'Активная аренда не найдена.')
            return
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        await self.deps.funpay.send_message(chat_id, f'До конца аренды осталось ~{minutes} мин.')

    async def stock(self, chat_id: int) -> None:
        """Tell how many free accounts are available for the renter's lot."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(chat_id, 'Активная аренда не найдена.')
            return
        free = await self.account_repo.count_free(rental.lot_id)
        await self.deps.funpay.send_message(chat_id, f'Свободных аккаунтов по лоту: {free}')

    async def faq(self, chat_id: int) -> None:
        """Send the help message."""
        await self.deps.funpay.send_message(chat_id, FAQ_TEXT)

    async def warn_expiring(self, rental_id: int) -> None:
        """Pre-expiry warning job."""
        rental = await self.rental_repo.get_or_none(id_=rental_id)
        if not rental or rental.status != RentalStatusEnum.ACTIVE or rental.chat_id is None:
            return
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        await self.deps.funpay.send_message(
            rental.chat_id,
            f'Аренда заканчивается через ~{minutes} мин. '
            f'Продлите заказ или сохраните прогресс — по истечении доступ закроется.',
        )
