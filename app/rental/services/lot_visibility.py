import contextlib
from logging import getLogger

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository
from app.runtime import RentalDeps


logger = getLogger(__name__)


async def sync_lot_visibility(session: AsyncSession, deps: RentalDeps, lot_id: int) -> None:
    """Показать/скрыть лот на FunPay по наличию свободных аккаунтов.

    Есть свободные → лот виден; распродан (0 свободных) → скрыт. Так
    покупатель не оплатит лот, который мы не сможем выдать. Лоты-продления
    пропускаем; лоты без funpay_lot_id — тоже (с предупреждением в лог).
    Ошибки не пробрасываем (видимость не должна ронять поток), но шлём алерт
    админу — иначе «лот не скрылся» молча.
    """
    lot = await LotRepository(session).get_or_none(id_=lot_id)
    if not lot or lot.is_extension:
        return
    if lot.funpay_lot_id is None:
        logger.warning('lot %s ("%s") без funpay_lot_id — видимость не меняем', lot_id, lot.title)
        return
    free = await AccountRepository(session).count_free(lot_id)
    # Виден на FunPay = лот включён у нас И есть свободные аккаунты.
    # Выключенный (или распроданный) лот скрываем.
    want_active = lot.active and free > 0
    try:
        await deps.funpay.set_lot_active(lot.funpay_lot_id, want_active)
    except Exception as exc:
        logger.exception('failed to sync FunPay visibility for lot %s', lot_id)
        action = 'показать' if want_active else 'скрыть'
        with contextlib.suppress(Exception):
            await deps.notifier.notify(
                f'⚠️ Не удалось {action} лот "{lot.title}" на FunPay '
                f'(оффер {lot.funpay_lot_id}): {exc}',
            )
