from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.rental.common.enums import AccountStatusEnum, ExtensionReasonEnum, RentalStatusEnum
from app.rental.funpay.events import NewOrderEvent
from app.rental.models.lot import Lot
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.extension import ExtensionRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.delivery import render_delivery
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.lot_visibility import sync_lot_visibility
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
    extension_repo: ClassVar[ExtensionRepository] = get_repository(ExtensionRepository)

    async def handle(self, event: NewOrderEvent) -> None:
        """Process a new paid order."""
        if await self.rental_repo.get_by_order_id(event.order_id):
            logger.info('order %s already processed, skip', event.order_id)
            return

        lots = await self.lot_repo.get_active_by_title(event.lot_title)
        if not lots:
            logger.warning('no active lot for title %r (order %s)', event.lot_title, event.order_id)
            await self.deps.notifier.notify(
                f'Заказ {event.order_id}: не найден активный лот "{event.lot_title}"',
            )
            return

        if lots[0].is_extension:
            await self._handle_extension(event, lots[0])
            return

        # Несколько лотов могут называться одинаково — берём первый со свободным
        # аккаунтом (pick_free_account блокирует строку FOR UPDATE SKIP LOCKED).
        lot = None
        account = None
        for candidate in lots:
            if candidate.is_extension:
                continue
            account = await self.account_repo.pick_free_account(candidate.id)
            if account:
                lot = candidate
                break
        if account is None or lot is None:
            await self._handle_no_free_account(event, event.lot_title)
            return

        await self.account_repo.update({'status': AccountStatusEnum.RENTED}, id_=account.id)

        # Кол-во купленных единиц умножает длительность (2 шт. = 2× времени).
        total_minutes = lot.duration_minutes * max(1, event.amount)
        now = datetime.now()
        expires_at = now + timedelta(minutes=total_minutes)
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
            minutes=total_minutes,
            game=lot.game or '',
        )
        await self.deps.funpay.send_message(event.chat_id, text)
        await sync_lot_visibility(self.session, self.deps, lot.id)
        logger.info('rental %s created for order %s (expires %s)', rental.id, event.order_id,
                    expires_at)

    async def _handle_extension(self, event: NewOrderEvent, lot: Lot) -> None:
        """Заказ на лот-продление → добавить время к активной аренде покупателя."""
        if await self.extension_repo.get_or_none(funpay_order_id=event.order_id):
            logger.info('extension order %s already processed, skip', event.order_id)
            return

        rentals = await self.rental_repo.get_active_by_buyer(event.buyer_id)
        if not rentals:
            await self.deps.funpay.send_message(
                event.chat_id,
                'У вас нет активной аренды для продления. Напишите продавцу.',
            )
            await self.deps.notifier.notify(
                f'Продление без активной аренды: заказ {event.order_id}, '
                f'покупатель {event.buyer_username}',
            )
            return

        target = rentals[0]  # ближайшая к истечению (get_active_by_buyer сортирует)
        if len(rentals) > 1:
            await self.deps.notifier.notify(
                f'У покупателя {event.buyer_username} {len(rentals)} активных аренд; '
                f'продлеваю ближайшую (аренда {target.id}, заказ {event.order_id}).',
            )
        added_minutes = lot.duration_minutes * max(1, event.amount)
        await ExtendRentalService(self.session, self.deps).extend_by_id(
            target.id,
            added_minutes,
            ExtensionReasonEnum.PURCHASE,
            order_id=event.order_id,
        )
        logger.info('extension order %s -> rental %s (+%s min)',
                    event.order_id, target.id, added_minutes)

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
