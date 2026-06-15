from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.common.enums import AccountStatusEnum
from app.rental.models.account import Account
from app.rental.repositories.base import Repository


class AccountRepository(Repository[Account]):
    model = Account

    async def pick_free_account(self, lot_id: int) -> Account | None:
        """Lock and return one free account for the lot.

        Использует FOR UPDATE SKIP LOCKED, чтобы два параллельных заказа
        не выбрали один и тот же аккаунт. Перевод в RENTED делает сервис
        в рамках той же транзакции.
        """
        query = (
            sa.select(Account)
            .where(
                Account.lot_id == lot_id,
                Account.status == AccountStatusEnum.FREE,
            )
            .order_by(Account.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        return await self.scalar(query)

    async def count_free(self, lot_id: int) -> int:
        """Count free accounts for the lot."""
        query = sa.select(sa.func.count(Account.id)).where(
            Account.lot_id == lot_id,
            Account.status == AccountStatusEnum.FREE,
        )
        result = await self.execute(query)
        return result.scalar() or 0

    async def counts_by_status(self) -> dict[AccountStatusEnum, int]:
        """Количество аккаунтов в разбивке по статусам (для дашборда)."""
        query = sa.select(Account.status, sa.func.count(Account.id)).group_by(Account.status)
        result = await self.execute(query)
        return {row[0]: row[1] for row in result.all()}

    async def list_by_lot(self, lot_id: int) -> Sequence[Account]:
        """Все аккаунты лота, по id (для списка в админке)."""
        query = sa.select(Account).where(Account.lot_id == lot_id).order_by(Account.id)
        return await self.scalars(query)
