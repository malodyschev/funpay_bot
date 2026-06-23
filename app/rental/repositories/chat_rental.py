from collections.abc import Sequence
from datetime import datetime, timedelta

import sqlalchemy as sa

from app.rental.common.enums import ChatRentalStatusEnum
from app.rental.models.chat_rental import ChatRental
from app.rental.repositories.base import Repository


class ChatRentalRepository(Repository[ChatRental]):
    model = ChatRental

    async def get_by_order_id(self, order_id: str) -> ChatRental | None:
        return await self.scalar(
            sa.select(ChatRental).where(ChatRental.funpay_order_id == order_id),
        )

    async def get_active_by_chat(self, chat_id: int) -> ChatRental | None:
        """Активная аренда этого чата (для !chat-code)."""
        query = (
            sa.select(ChatRental)
            .where(
                ChatRental.chat_id == chat_id,
                ChatRental.status == ChatRentalStatusEnum.ACTIVE,
            )
            .order_by(ChatRental.expires_at.desc())
            .limit(1)
        )
        return await self.scalar(query)

    async def count_active_by_account(self, chat_account_id: int) -> int:
        """Сколько слотов занято на аккаунте (активные аренды)."""
        query = sa.select(sa.func.count(ChatRental.id)).where(
            ChatRental.chat_account_id == chat_account_id,
            ChatRental.status == ChatRentalStatusEnum.ACTIVE,
        )
        result = await self.execute(query)
        return result.scalar() or 0

    async def count_active_in_category(self, category_id: int) -> int:
        """Сколько слотов занято во всём пуле категории (для авто-скрытия лотов)."""
        from app.rental.models.chat_account import ChatAccount
        query = (
            sa.select(sa.func.count(ChatRental.id))
            .join(ChatAccount, ChatRental.chat_account_id == ChatAccount.id)
            .where(
                ChatAccount.category_id == category_id,
                ChatRental.status == ChatRentalStatusEnum.ACTIVE,
            )
        )
        result = await self.execute(query)
        return result.scalar() or 0

    async def active_load_by_category(self, category_id: int) -> dict[int, int]:
        """Загрузка каждого аккаунта пула за один запрос: {chat_account_id: занято слотов}.

        Аккаунты без активных аренд в словарь не попадают (читатель берёт .get(id, 0)).
        """
        from app.rental.models.chat_account import ChatAccount
        query = (
            sa.select(ChatRental.chat_account_id, sa.func.count(ChatRental.id))
            .join(ChatAccount, ChatRental.chat_account_id == ChatAccount.id)
            .where(
                ChatAccount.category_id == category_id,
                ChatRental.status == ChatRentalStatusEnum.ACTIVE,
            )
            .group_by(ChatRental.chat_account_id)
        )
        result = await self.execute(query)
        return dict(result.all())

    async def get_active(self) -> Sequence[ChatRental]:
        """Все активные Chat-аренды (для списка в админке), ближайшие к концу первыми."""
        query = (
            sa.select(ChatRental)
            .where(ChatRental.status == ChatRentalStatusEnum.ACTIVE)
            .order_by(ChatRental.expires_at)
        )
        return await self.scalars(query)

    async def count_active(self) -> int:
        """Число активных Chat-аренд (для счётчика в меню/дашборде)."""
        query = sa.select(sa.func.count(ChatRental.id)).where(
            ChatRental.status == ChatRentalStatusEnum.ACTIVE,
        )
        result = await self.execute(query)
        return result.scalar() or 0

    async def active_by_account(self, chat_account_id: int) -> Sequence[ChatRental]:
        """Активные аренды аккаунта (для замены/кика)."""
        query = sa.select(ChatRental).where(
            ChatRental.chat_account_id == chat_account_id,
            ChatRental.status == ChatRentalStatusEnum.ACTIVE,
        )
        return await self.scalars(query)

    async def get_last_by_chat(self, chat_id: int) -> ChatRental | None:
        """Последняя аренда чата (любого статуса) — отличить «истекла» от «не было».

        У покупателя может быть несколько аренд на один чат, поэтому берём по id
        с limit 1 (а не get_or_none, который падает на нескольких строках).
        """
        query = (
            sa.select(ChatRental)
            .where(ChatRental.chat_id == chat_id)
            .order_by(ChatRental.id.desc())
            .limit(1)
        )
        return await self.scalar(query)

    async def due(self, now: datetime) -> Sequence[ChatRental]:
        """Активные аренды с истёкшим сроком (для поллера)."""
        query = sa.select(ChatRental).where(
            ChatRental.status == ChatRentalStatusEnum.ACTIVE,
            ChatRental.expires_at <= now,
        )
        return await self.scalars(query)

    async def claim_due_for_warning(self, warn_minutes: int) -> Sequence[ChatRental]:
        """Захватить аренды, которым пора предупреждение об окончании.

        Помечаем warned=True под блокировкой (FOR UPDATE SKIP LOCKED), чтобы не
        слать повторно и чтобы несколько инстансов не задублировали уведомление.
        """
        now = datetime.now()
        query = (
            sa.select(ChatRental)
            .where(
                ChatRental.status == ChatRentalStatusEnum.ACTIVE,
                ChatRental.warned.is_(False),
                ChatRental.expires_at > now,
                ChatRental.expires_at <= now + timedelta(minutes=warn_minutes),
            )
            .with_for_update(skip_locked=True)
        )
        rentals = list(await self.scalars(query))
        if rentals:
            await self.execute(
                sa.update(ChatRental)
                .where(ChatRental.id.in_([r.id for r in rentals]))
                .values(warned=True),
            )
            await self.session.commit()
        return rentals
