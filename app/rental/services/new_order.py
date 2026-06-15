from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.rental.common.enums import AccountStatusEnum, RentalStatusEnum
from app.rental.funpay.events import NewOrderEvent
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.delivery import render_delivery
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class NewOrderService:
    """W1. Новый заказ → выбор аккаунта → выдача → таймер."""

    session: AsyncSession
    deps: RentalDeps
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)

    async def handle(self, event: NewOrderEvent) -> None:
        """Process a new paid order."""
        if await self.rental_repo.get_by_order_id(event.order_id):
            logger.info('order %s already processed, skip', event.order_id)
            return

        lot = await self.lot_repo.get_active_by_title(event.lot_title)
        if not lot:
            logger.warning('no active lot for title %r (order %s)', event.lot_title, event.order_id)
            await self.deps.notifier.notify(
                f'Заказ {event.order_id}: не найден активный лот "{event.lot_title}"',
            )
            return

        account = await self.account_repo.pick_free_account(lot.id)
        if not account:
            await self._handle_no_free_account(event, lot.title)
            return

        await self.account_repo.update({'status': AccountStatusEnum.RENTED}, id_=account.id)

        now = datetime.now()
        expires_at = now + timedelta(minutes=lot.duration_minutes)
        rental = await self.rental_repo.create({
            'account_id': account.id,
            'lot_id': lot.id,
            'funpay_order_id': event.order_id,
            'buyer_id': event.buyer_id,
            'buyer_username': event.buyer_username,
            'chat_id': event.chat_id,
            'started_at': now,
            'expires_at': expires_at,
            'status': RentalStatusEnum.ACTIVE,
        })

        text = render_delivery(
            lot.delivery_template,
            login=account.login,
            password=decrypt(account.password_enc),
            minutes=lot.duration_minutes,
            game=lot.game or '',
        )
        await self.deps.funpay.send_message(event.chat_id, text)
        logger.info('rental %s created for order %s (expires %s)', rental.id, event.order_id,
                    expires_at)

    async def _handle_no_free_account(self, event: NewOrderEvent, lot_title: str) -> None:
        """W5. Нет свободного аккаунта → алерт админу + запрос возврата."""
        logger.warning('no free account for lot %r (order %s)', lot_title, event.order_id)
        await self.deps.funpay.send_message(
            event.chat_id,
            'Извините, сейчас нет свободных аккаунтов. Оформляется возврат.',
        )
        await self.deps.notifier.notify(
            f'Нет свободных аккаунтов под лот "{lot_title}" (заказ {event.order_id})',
        )
        await self.deps.notifier.request_refund(event.order_id, 'no free account')
