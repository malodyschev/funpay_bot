from logging import getLogger

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository
from app.runtime import RentalDeps


logger = getLogger(__name__)


async def sync_lot_visibility(session: AsyncSession, deps: RentalDeps, lot_id: int) -> None:
    """Показать/скрыть лот на FunPay по наличию свободных аккаунтов.

    Есть свободные → лот виден; распродан (0 свободных) → скрыт. Так
    покупатель не оплатит лот, который мы не сможем выдать. Лоты без
    funpay_lot_id и лоты-продления пропускаем. Ошибки не пробрасываем —
    видимость не должна ронять основной поток.
    """
    lot = await LotRepository(session).get_or_none(id_=lot_id)
    if not lot or lot.funpay_lot_id is None or lot.is_extension:
        return
    free = await AccountRepository(session).count_free(lot_id)
    try:
        await deps.funpay.set_lot_active(lot.funpay_lot_id, free > 0)
    except Exception:
        logger.exception('failed to sync FunPay visibility for lot %s', lot_id)
