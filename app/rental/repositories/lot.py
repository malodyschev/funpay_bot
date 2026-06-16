from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.models.lot import Lot
from app.rental.repositories.base import Repository


class LotRepository(Repository[Lot]):
    model = Lot

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
