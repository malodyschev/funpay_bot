from dataclasses import dataclass
from datetime import timedelta
from logging import getLogger
from typing import ClassVar

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.enums import ExtensionReasonEnum, RentalStatusEnum
from app.rental.repositories.extension import ExtensionRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class ExtendRentalService:
    """W4. Продление аренды (за отзыв или вручную админом)."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    extension_repo: ClassVar[ExtensionRepository] = get_repository(ExtensionRepository)

    async def extend_by_order(
        self,
        order_id: str,
        minutes: int,
        reason: ExtensionReasonEnum,
    ) -> None:
        """Extend an active rental found by FunPay order id."""
        rental = await self.rental_repo.get_by_order_id(order_id)
        if not rental:
            logger.info('no rental for order %s, skip extension', order_id)
            return
        await self._extend(rental.id, minutes, reason)

    async def extend_by_id(
        self,
        rental_id: int,
        minutes: int,
        reason: ExtensionReasonEnum,
        order_id: str | None = None,
    ) -> None:
        """Extend an active rental by internal id (admin command / purchase)."""
        await self._extend(rental_id, minutes, reason, order_id)

    async def _extend(
        self,
        rental_id: int,
        minutes: int,
        reason: ExtensionReasonEnum,
        order_id: str | None = None,
    ) -> None:
        rental = await self.rental_repo.get_or_none(id_=rental_id)
        if not rental or rental.status != RentalStatusEnum.ACTIVE:
            logger.info('rental %s is not active, skip extension', rental_id)
            return

        new_expires_at = rental.expires_at + timedelta(minutes=minutes)
        # АТОМАРНО: +время к аренде и запись extension в одной транзакции.
        # UNIQUE(extensions.funpay_order_id) ловит дубль заказа продления — при
        # гонке проигравший откатывается, время НЕ добавляется дважды.
        try:
            await self.rental_repo.update(
                {
                    'expires_at': new_expires_at,
                    'extended_minutes': rental.extended_minutes + minutes,
                    'warned': False,  # перед новым сроком предупредим заново
                },
                id_=rental.id,
                commit=False,
            )
            await self.extension_repo.create({
                'rental_id': rental.id,
                'minutes_added': minutes,
                'reason': reason,
                'funpay_order_id': order_id,
            }, commit=False)
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            logger.info('extension order %s дубль — время не добавляю повторно', order_id)
            return

        if rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                f'🎉✨ Аренда продлена на +{minutes} мин! ✨🎉\n'
                '⏳ Время уже добавлено к вашей сессии. Приятной игры! 🎮🔥',
            )
        logger.info('rental %s extended by %s min (%s)', rental.id, minutes, reason.name)
