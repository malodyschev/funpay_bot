from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.common.enums import AccountStatusEnum
from app.rental.models.account import Account
from app.rental.models.lot import Lot
from app.rental.repositories.base import Repository


class LotRepository(Repository[Lot]):
    model = Lot

    async def free_account_counts(self) -> Sequence[tuple[Lot, int]]:
        """Активные лоты аренды и число свободных аккаунтов по каждому (для !free-all)."""
        free_flag = sa.case((Account.status == AccountStatusEnum.FREE, 1), else_=0)
        query = (
            sa.select(Lot, sa.func.coalesce(sa.func.sum(free_flag), 0))
            .outerjoin(Account, Account.lot_id == Lot.id)
            .where(
                Lot.active.is_(True),
                Lot.is_extension.is_(False),
                Lot.removed.is_(False),
            )
            .group_by(Lot.id)
            .order_by(Lot.title)
        )
        result = await self.execute(query)
        return [(row[0], int(row[1])) for row in result.all()]

    async def get_extension_lot(self) -> Lot | None:
        """Активный лот-продление (пока он один на весь бот — для ссылки в !extend)."""
        query = (
            sa.select(Lot)
            .where(
                Lot.is_extension.is_(True),
                Lot.active.is_(True),
                Lot.removed.is_(False),
            )
            .order_by(Lot.id)
            .limit(1)
        )
        return await self.scalar(query)

    async def get_active_by_title(self, title: str) -> Sequence[Lot]:
        """Все активные лоты с этим названием (названия не уникальны — несколько
        офферов FunPay могут называться одинаково; заказ сопоставляем по названию).
        """
        query = (
            sa.select(Lot)
            .where(Lot.title == title, Lot.active.is_(True))
            .order_by(Lot.id)
        )
        return await self.scalars(query)

    async def get_unlinked_by_title(self, title: str) -> Lot | None:
        """Лот с этим названием, ещё не привязанный к офферу FunPay (для синка)."""
        query = (
            sa.select(Lot)
            .where(Lot.title == title, Lot.funpay_lot_id.is_(None))
            .order_by(Lot.id)
            .limit(1)
        )
        return await self.scalar(query)

    async def active_linked(self) -> Sequence[Lot]:
        """Наши активные лоты, привязанные к офферу FunPay (для сверки удалений)."""
        query = sa.select(Lot).where(Lot.active.is_(True), Lot.funpay_lot_id.is_not(None))
        return await self.scalars(query)

    async def linked(self) -> Sequence[Lot]:
        """Все лоты, привязанные к офферу FunPay (для полной сверки 1-в-1)."""
        query = sa.select(Lot).where(Lot.funpay_lot_id.is_not(None))
        return await self.scalars(query)
