import asyncio
from dataclasses import dataclass
from logging import getLogger

import FunPayAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository


logger = getLogger(__name__)


@dataclass
class SyncResult:
    """Итоги синхронизации лотов с FunPay."""

    created: int = 0  # новые офферы → черновики
    updated: int = 0  # обновлены/реактивированы
    deactivated: int = 0  # продавец выключил оффер → у нас неактивен
    removed: int = 0  # оффер удалён на FunPay → скрыт из админки

    def summary(self) -> str:
        return (
            f'создано {self.created}, обновлено {self.updated}, '
            f'выключено {self.deactivated}, удалено {self.removed}'
        )


async def sync_lots(session: AsyncSession, account: FunPayAPI.Account) -> SyncResult:
    """Полная сверка офферов продавца 1-в-1 с FunPay.

    Источник — страница управления лотами (`get_my_subcategory_lots`), которая
    видит И активные, И неактивные офферы (публичный профиль — только активные).

    - оффер активен → лот активен;
    - оффер неактивен → лот неактивен (показываем, помечен), КРОМЕ случая нашей
      авто-скрытки распроданного (free=0) — тогда оставляем активным;
    - оффер удалён (исчез из подкатегории) → лот removed=True (в админке не виден);
    - новый оффер → черновик (active=False): донастроить длительность+аккаунт.
    """
    repo = LotRepository(session)
    account_repo = AccountRepository(session)

    # Подкатегории: где есть активные офферы + где есть наши привязанные лоты.
    profile = await asyncio.to_thread(account.get_user, account.id)
    active_lots = await asyncio.to_thread(profile.get_lots)
    subcat_ids: set[int] = {
        sub.id for lot in active_lots if (sub := getattr(lot, 'subcategory', None)) and sub.id
    }
    for lot in await repo.linked():
        if lot.funpay_node_id:
            subcat_ids.add(lot.funpay_node_id)

    # Полный список офферов по подкатегориям (только успешно загруженные сверяем).
    offers: dict[int, object] = {}
    fetched_subcats: set[int] = set()
    for sub_id in subcat_ids:
        try:
            my_lots = await asyncio.to_thread(account.get_my_subcategory_lots, sub_id)
        except Exception:
            logger.exception('sync: не удалось получить лоты подкатегории %s', sub_id)
            continue
        fetched_subcats.add(sub_id)
        for offer in my_lots:
            offers[int(offer.id)] = offer

    result = SyncResult()
    for offer in offers.values():
        try:
            await _upsert_offer(repo, account_repo, offer, result)
        except Exception:
            logger.exception('sync: не удалось обработать оффер %s', getattr(offer, 'id', '?'))
            await session.rollback()

    # Удалённые: наши привязанные лоты, чья подкатегория загрузилась, но оффер исчез.
    for lot in await repo.linked():
        if lot.removed or lot.funpay_node_id not in fetched_subcats:
            continue
        if int(lot.funpay_lot_id) not in offers:
            await repo.update({'removed': True, 'active': False}, id_=lot.id)
            result.removed += 1

    logger.info('funpay lot sync: %s', result.summary())
    return result


async def _upsert_offer(
    repo: LotRepository,
    account_repo: AccountRepository,
    offer: object,
    result: SyncResult,
) -> None:
    """Создать/обновить лот по офферу из get_my_subcategory_lots."""
    offer_id = int(offer.id)
    title = (getattr(offer, 'description', None) or f'lot {offer_id}')[:500]
    fp_active = bool(getattr(offer, 'active', True))
    sub_id = getattr(getattr(offer, 'subcategory', None), 'id', None)

    existing = await repo.get_or_none(funpay_lot_id=offer_id)
    if not existing:
        # привязать к ручному непривязанному лоту с тем же названием, иначе создать
        unlinked = await repo.get_unlinked_by_title(title)
        if unlinked:
            await repo.update(
                {'funpay_lot_id': offer_id, 'funpay_node_id': sub_id, 'removed': False},
                id_=unlinked.id,
            )
            result.updated += 1
        else:
            await repo.create({
                'funpay_lot_id': offer_id,
                'funpay_node_id': sub_id,
                'title': title,
                'price': getattr(offer, 'price', None),
                'duration_minutes': 0,
                'delivery_template': DEFAULT_DELIVERY_TEMPLATE,
                'active': False,  # черновик — донастроить и включить
                'is_extension': False,
                'removed': False,
            })
            result.created += 1
        return

    # Лот уже есть. Синк только ДЕАКТИВИРУЕТ (отражает выключение продавцом);
    # активацию НЕ навязываем — черновик/выключенный включает админ после настройки.
    update_data: dict = {'price': getattr(offer, 'price', None), 'removed': False}
    if not fp_active and existing.active:
        free = await account_repo.count_free(existing.id)
        if free > 0:  # free>0 → продавец выключил; free==0 → наша скрытка, не трогаем
            update_data['active'] = False
            result.deactivated += 1
    await repo.update(update_data, id_=existing.id)
    result.updated += 1
