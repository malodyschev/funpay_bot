from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from app.rental.common.enums import XRentalStatusEnum
from app.rental.models.x_rental import XRental
from app.rental.repositories.base import Repository


class XRentalRepository(Repository[XRental]):
    model = XRental

    async def get_by_order_id(self, order_id: str) -> XRental | None:
        return await self.scalar(
            sa.select(XRental).where(XRental.funpay_order_id == order_id),
        )

    async def get_active_by_chat(self, chat_id: int) -> XRental | None:
        """Активная аренда этого чата (для !x-code)."""
        query = (
            sa.select(XRental)
            .where(
                XRental.chat_id == chat_id,
                XRental.status == XRentalStatusEnum.ACTIVE,
            )
            .order_by(XRental.expires_at.desc())
            .limit(1)
        )
        return await self.scalar(query)

    async def count_active_by_account(self, x_account_id: int) -> int:
        """Сколько слотов занято на аккаунте (активные аренды)."""
        query = sa.select(sa.func.count(XRental.id)).where(
            XRental.x_account_id == x_account_id,
            XRental.status == XRentalStatusEnum.ACTIVE,
        )
        result = await self.execute(query)
        return result.scalar() or 0

    async def active_by_account(self, x_account_id: int) -> Sequence[XRental]:
        """Активные аренды аккаунта (для замены/кика)."""
        query = sa.select(XRental).where(
            XRental.x_account_id == x_account_id,
            XRental.status == XRentalStatusEnum.ACTIVE,
        )
        return await self.scalars(query)

    async def due(self, now: datetime) -> Sequence[XRental]:
        """Активные аренды с истёкшим сроком (для поллера)."""
        query = sa.select(XRental).where(
            XRental.status == XRentalStatusEnum.ACTIVE,
            XRental.expires_at <= now,
        )
        return await self.scalars(query)
