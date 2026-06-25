from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.models.blocked_buyer import BlockedBuyer
from app.rental.repositories.base import Repository


def normalize_username(username: str) -> str:
    """Нормализовать ник для матчинга: без пробелов, без ведущего @, без регистра."""
    return username.strip().lstrip('@').casefold()


class BlockedBuyerRepository(Repository[BlockedBuyer]):
    model = BlockedBuyer

    async def is_blocked(self, username: str | None) -> bool:
        """Покупатель с таким ником в чёрном списке? (без регистра / @)."""
        if not username:
            return False
        query = sa.select(sa.func.count(BlockedBuyer.id)).where(
            BlockedBuyer.username_norm == normalize_username(username),
        )
        return bool((await self.execute(query)).scalar())

    async def list_all(self) -> Sequence[BlockedBuyer]:
        """Все заблокированные ники (по алфавиту)."""
        return await self.scalars(
            sa.select(BlockedBuyer).order_by(BlockedBuyer.username_norm),
        )

    async def get_by_username(self, username: str) -> BlockedBuyer | None:
        return await self.scalar(
            sa.select(BlockedBuyer).where(
                BlockedBuyer.username_norm == normalize_username(username),
            ),
        )
