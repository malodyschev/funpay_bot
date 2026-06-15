from app.rental.models.lot import Lot
from app.rental.repositories.base import Repository


class LotRepository(Repository[Lot]):
    model = Lot

    async def get_active_by_title(self, title: str) -> Lot | None:
        """Найти активный лот по точному названию из FunPay (так заказ
        сопоставляется с нашим лотом и его настройками).
        """
        return await self.get_or_none(title=title, active=True)
