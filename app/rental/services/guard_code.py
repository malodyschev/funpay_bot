from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.code_log import append_code_time
from app.rental.common.commands import BLOCKED_BUYER_MESSAGE
from app.rental.common.exceptions import SteamModuleError
from app.rental.funpay.events import NewMessageEvent
from app.rental.providers.registry import get_provider
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.blocked_buyer import BlockedBuyerRepository
from app.rental.repositories.category import CategoryRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class GuardCodeService:
    """W2. Команда !код → выдать текущий Steam Guard код активному арендатору."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)
    category_repo: ClassVar[CategoryRepository] = get_repository(CategoryRepository)
    blocked_repo: ClassVar[BlockedBuyerRepository] = get_repository(BlockedBuyerRepository)

    async def handle(self, event: NewMessageEvent) -> None:
        """Send the current Guard code to the active renter of this chat."""
        rental = await self.rental_repo.get_active_by_chat(event.chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                event.chat_id,
                '📱 Код Steam Guard выдаётся только во время активной аренды.\n'
                'Сначала оплатите заказ и возьмите данные командой !acc. '
                'Если уже оплатили — напишите !admin.',
            )
            return

        # Чёрный список — код не выдаём.
        if await self.blocked_repo.is_blocked(rental.buyer_username):
            await self.deps.funpay.send_message(event.chat_id, BLOCKED_BUYER_MESSAGE)
            return

        account = await self.account_repo.get(rental.account_id)
        lot = await self.lot_repo.get_or_none(id_=account.lot_id)
        _, provider_enum = await self.category_repo.resolve(lot.category_id if lot else None)
        provider = get_provider(provider_enum, self.deps)
        try:
            code = await provider.generate_code(account)
        except SteamModuleError:
            logger.exception('failed to generate guard code for account %s', account.id)
            await self.deps.funpay.send_message(
                event.chat_id,
                '⚠️ Не получилось сгенерировать код прямо сейчас. '
                'Попробуйте ещё раз через минуту или напишите !admin.',
            )
            return

        await self.deps.funpay.send_message(event.chat_id, f'📱 Код Steam Guard: {code}')

        # Фиксируем вход (= запрос кода) в журнал аренды. Алерт на каждый запрос НЕ
        # шлём — журнал виден админу в карточке аренды и при кике по истечении.
        await self.rental_repo.update(
            {'code_log': append_code_time(rental.code_log, datetime.now())}, id_=rental.id,
        )
