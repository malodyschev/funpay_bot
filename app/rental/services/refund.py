from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.enums import AccountStatusEnum, RentalStatusEnum
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.lot_visibility import sync_lot_visibility
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class RefundService:
    """W5. Исполнение возврата заказа (после подтверждения админом)."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)

    async def execute(self, order_id: str) -> None:
        """Refund the order and release the account if one was assigned."""
        await self.deps.funpay.refund_order(order_id)

        rental = await self.rental_repo.get_by_order_id(order_id)
        if not rental:
            logger.info('refunded order %s without a rental record', order_id)
            return

        # Возврат на FunPay уже выполнен выше (внешний вызов). Статусы в БД —
        # атомарно: аренда REFUNDED + аккаунт FREE в одной транзакции.
        await self.rental_repo.update(
            {'status': RentalStatusEnum.REFUNDED}, id_=rental.id, commit=False,
        )
        await self.account_repo.update(
            {'status': AccountStatusEnum.FREE}, id_=rental.account_id, commit=False,
        )
        await self.session.commit()
        await sync_lot_visibility(self.session, self.deps, rental.lot_id)
        if rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                '✅ Возврат оформлен — средства вернутся на ваш баланс FunPay. '
                'Доступ к аккаунту закрыт.',
            )
        logger.info('order %s refunded, rental %s closed', order_id, rental.id)

    async def decline(self, order_id: str) -> None:
        """Отказ в возврате: уведомить покупателя (если у заказа есть чат)."""
        rental = await self.rental_repo.get_by_order_id(order_id)
        if rental and rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                '↩️ Продавец отклонил запрос на возврат. '
                'Если есть вопросы — напишите !admin.',
            )
