from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.enums import AccountStatusEnum, ChatRentalStatusEnum, RentalStatusEnum
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.chat_account import ChatAccountRepository
from app.rental.repositories.chat_rental import ChatRentalRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.chat_rental import ChatRentalService
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
    chat_rental_repo: ClassVar[ChatRentalRepository] = get_repository(ChatRentalRepository)
    chat_account_repo: ClassVar[ChatAccountRepository] = get_repository(ChatAccountRepository)

    async def execute(self, order_id: str) -> None:
        """Refund the order and release the account if one was assigned."""
        await self.deps.funpay.refund_order(order_id)

        rental = await self.rental_repo.get_by_order_id(order_id)
        if not rental:
            await self._refund_chat(order_id)
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

    async def _refund_chat(self, order_id: str) -> None:
        """Возврат Chat-аренды: закрыть аренду (освободить слот) + уведомить покупателя."""
        rental = await self.chat_rental_repo.get_by_order_id(order_id)
        if not rental:
            logger.info('refunded order %s without a rental record', order_id)
            return
        account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
        await self.chat_rental_repo.update(
            {'status': ChatRentalStatusEnum.CLOSED}, id_=rental.id,
        )
        if account and account.category_id is not None:
            await ChatRentalService(self.session, self.deps).sync_pool_visibility(
                account.category_id,
            )
        if rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                '✅ Возврат оформлен — средства вернутся на ваш баланс FunPay.',
            )
        logger.info('chat order %s refunded, rental %s closed', order_id, rental.id)

    async def decline(self, order_id: str) -> None:
        """Отказ в возврате: уведомить покупателя (если у заказа есть чат)."""
        rental = await self.rental_repo.get_by_order_id(order_id)
        if rental is None:
            rental = await self.chat_rental_repo.get_by_order_id(order_id)
        if rental and rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                '↩️ Продавец отклонил запрос на возврат. '
                'Если есть вопросы — напишите !admin.',
            )
