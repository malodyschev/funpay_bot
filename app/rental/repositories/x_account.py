from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.models.x_account import XAccount
from app.rental.repositories.base import Repository


class XAccountRepository(Repository[XAccount]):
    model = XAccount

    async def list_by_category(self, category_id: int) -> Sequence[XAccount]:
        """Аккаунты пула категории (не выведенные из пула), по id."""
        query = (
            sa.select(XAccount)
            .where(XAccount.category_id == category_id, XAccount.removed.is_(False))
            .order_by(XAccount.id)
        )
        return await self.scalars(query)
