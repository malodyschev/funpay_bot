import asyncio
from logging import getLogger

import FunPayAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository


logger = getLogger(__name__)


async def sync_lots(session: AsyncSession, account: FunPayAPI.Account) -> tuple[int, int, int]:
    """Полная синхронизация офферов продавца с FunPay.

    Новый оффер → ЧЕРНОВИК лота (active=False, duration=0): донастроить в
    админке (длительность+аккаунт) и включить. Существующий → обновляем
    title/price. Пропавший из активных на FunPay (удалён/деактивирован
    продавцом) → помечаем active=False у нас. Исключение — наш авто-скрытый
    при распродаже лот (free=0): он тоже исчезает из активных на FunPay,
    но это наша скрытка, его не трогаем.

    Returns:
        (создано, обновлено, деактивировано).
    """
    profile = await asyncio.to_thread(account.get_user, account.id)
    fp_lots = await asyncio.to_thread(profile.get_lots)

    repo = LotRepository(session)
    created = updated = 0
    fetched_ids: set[int] = set()
    for fp in fp_lots:
        fetched_ids.add(fp.id)
        try:
            if await _upsert_lot(repo, fp):
                created += 1
            else:
                updated += 1
        except Exception:
            # Одна проблемная запись не должна ронять синк целиком.
            logger.exception('sync: не удалось обработать оффер %s', getattr(fp, 'id', '?'))
            await session.rollback()

    deactivated = await _deactivate_removed(session, fetched_ids)
    logger.info(
        'funpay lot sync: created=%s updated=%s deactivated=%s', created, updated, deactivated,
    )
    return created, updated, deactivated


async def _deactivate_removed(session: AsyncSession, fetched_ids: set[int]) -> int:
    """Выключить наши активные лоты, пропавшие из активных на FunPay.

    Если у лота есть свободные аккаунты, но его нет среди активных офферов —
    значит продавец его убрал/деактивировал. Распроданные (free=0) не трогаем:
    это наш авто-hide, оффер вернётся при освобождении аккаунта.
    """
    repo = LotRepository(session)
    account_repo = AccountRepository(session)
    deactivated = 0
    for lot in await repo.active_linked():
        if lot.funpay_lot_id in fetched_ids:
            continue
        if await account_repo.count_free(lot.id) > 0:
            await repo.update({'active': False}, id_=lot.id)
            deactivated += 1
    return deactivated


async def _upsert_lot(repo: LotRepository, fp) -> bool:
    """Создать/обновить лот по одному офферу FunPay. True — если создан новый."""
    existing = await repo.get_or_none(funpay_lot_id=fp.id)
    if existing:
        await repo.update(
            {'title': fp.title or existing.title, 'price': fp.price},
            id_=existing.id,
        )
        return False

    # Есть НЕпривязанный лот с таким названием (создан вручную) → привязываем.
    # Названия не уникальны: другие офферы с тем же именем создадутся отдельно.
    unlinked = await repo.get_unlinked_by_title(fp.title) if fp.title else None
    if unlinked:
        await repo.update({'funpay_lot_id': fp.id, 'price': fp.price}, id_=unlinked.id)
        return False

    await repo.create({
        'funpay_lot_id': fp.id,
        'funpay_node_id': getattr(fp.subcategory, 'id', None),
        'title': fp.title or f'lot {fp.id}',
        'price': fp.price,
        'duration_minutes': 0,
        'delivery_template': DEFAULT_DELIVERY_TEMPLATE,
        'active': False,
        'is_extension': False,
    })
    return True
