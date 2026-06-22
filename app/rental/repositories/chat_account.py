from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.models.chat_account import ChatAccount
from app.rental.repositories.base import Repository


class ChatAccountRepository(Repository[ChatAccount]):
    model = ChatAccount

    async def list_by_category(self, category_id: int) -> Sequence[ChatAccount]:
        """Аккаунты пула категории (не выведенные из пула), по id."""
        query = (
            sa.select(ChatAccount)
            .where(ChatAccount.category_id == category_id, ChatAccount.removed.is_(False))
            .order_by(ChatAccount.id)
        )
        return await self.scalars(query)

    async def lock(self, account_id: int) -> ChatAccount | None:
        """Заблокировать строку аккаунта (FOR UPDATE) до конца транзакции.

        Чтобы два одновременных заказа не превысили вместимость одного аккаунта.
        """
        query = (
            sa.select(ChatAccount)
            .where(ChatAccount.id == account_id, ChatAccount.removed.is_(False))
            .with_for_update()
        )
        return await self.scalar(query)
