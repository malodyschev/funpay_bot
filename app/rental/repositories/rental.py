from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa

from app.rental.common.enums import RentalStatusEnum
from app.rental.models.rental import Rental
from app.rental.repositories.base import Repository


class RentalRepository(Repository[Rental]):
    model = Rental

    async def get_by_order_id(self, funpay_order_id: str) -> Rental | None:
        """Найти аренду по номеру заказа FunPay (ключ идемпотентности — чтобы
        не выдать один заказ дважды).
        """
        return await self.get_or_none(funpay_order_id=funpay_order_id)

    async def get_active_by_chat(self, chat_id: int) -> Rental | None:
        """Найти активную аренду по чату FunPay (для команд !код, !время)."""
        return await self.get_or_none(chat_id=chat_id, status=RentalStatusEnum.ACTIVE)

    async def get_active(self) -> Sequence[Rental]:
        """Все активные аренды (для дашборда/списка в админке)."""
        query = (
            sa.select(Rental)
            .where(Rental.status == RentalStatusEnum.ACTIVE)
            .order_by(Rental.expires_at)
        )
        return await self.scalars(query)

    async def claim_due_for_expiry(self) -> list[int]:
        """Захватить истёкшие активные аренды под обработку (источник истины — БД).

        FOR UPDATE SKIP LOCKED: при нескольких инстансах каждую аренду заберёт
        только один воркер. Сразу переводим в EXPIRING, чтобы не выбрать повторно,
        и коммитим (блокировки снимаются до медленной деавторизации в Steam).

        Returns:
            id аренд, которые этот инстанс взял на обработку.
        """
        query = (
            sa.select(Rental)
            .where(
                Rental.status == RentalStatusEnum.ACTIVE,
                Rental.expires_at <= datetime.now(),
            )
            .order_by(Rental.expires_at)
            .with_for_update(skip_locked=True)
        )
        rentals = await self.scalars(query)
        ids = [r.id for r in rentals]
        if ids:
            await self.execute(
                sa.update(Rental)
                .where(Rental.id.in_(ids))
                .values(status=RentalStatusEnum.EXPIRING),
            )
            await self.session.commit()
        return ids

    async def claim_due_for_warning(self, warn_minutes: int) -> list[int]:
        """Захватить аренды, которым пора отправить предупреждение об окончании.

        Помечаем warned=True под блокировкой, чтобы не слать повторно и чтобы
        несколько инстансов не задублировали уведомление.
        """
        now = datetime.now()
        query = (
            sa.select(Rental)
            .where(
                Rental.status == RentalStatusEnum.ACTIVE,
                Rental.warned.is_(False),
                Rental.expires_at > now,
                Rental.expires_at <= now + timedelta(minutes=warn_minutes),
            )
            .with_for_update(skip_locked=True)
        )
        rentals = await self.scalars(query)
        ids = [r.id for r in rentals]
        if ids:
            await self.execute(
                sa.update(Rental).where(Rental.id.in_(ids)).values(warned=True),
            )
            await self.session.commit()
        return ids

    async def get_active_by_account(self, account_id: int) -> Rental | None:
        """Активная аренда конкретного аккаунта (для карточки/действий админки)."""
        return await self.get_or_none(account_id=account_id, status=RentalStatusEnum.ACTIVE)

    async def count_active(self) -> int:
        """Число активных аренд (для дашборда)."""
        query = sa.select(sa.func.count(Rental.id)).where(
            Rental.status == RentalStatusEnum.ACTIVE,
        )
        result = await self.execute(query)
        return result.scalar() or 0
