import asyncio
from logging import getLogger

import FunPayAPI
from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.repositories.lot import LotRepository


logger = getLogger(__name__)


async def sync_lots(session: AsyncSession, account: FunPayAPI.Account) -> tuple[int, int]:
    """Подтянуть офферы продавца с FunPay в нашу таблицу лотов.

    Новый оффер → создаём ЧЕРНОВИК лота (active=False, duration=0): его нужно
    донастроить в админке (длительность + аккаунт), затем активировать —
    пока active=False, заказ по нему не обрабатывается. Существующий лот
    (по funpay_lot_id или по совпадающему названию) — обновляем title/price.

    Returns:
        (создано, обновлено).
    """
    profile = await asyncio.to_thread(account.get_user, account.id)
    fp_lots = await asyncio.to_thread(profile.get_lots)

    repo = LotRepository(session)
    created = updated = 0
    for fp in fp_lots:
        existing = await repo.get_or_none(funpay_lot_id=fp.id)
        if existing:
            await repo.update(
                {'title': fp.title or existing.title, 'price': fp.price},
                id_=existing.id,
            )
            updated += 1
            continue

        # Есть НЕпривязанный лот с таким названием (создан вручную) → привязываем.
        # Названия не уникальны: другие офферы с тем же именем создадутся отдельно.
        unlinked = await repo.get_unlinked_by_title(fp.title) if fp.title else None
        if unlinked:
            await repo.update({'funpay_lot_id': fp.id, 'price': fp.price}, id_=unlinked.id)
            updated += 1
            continue

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
        created += 1

    logger.info('funpay lot sync: created=%s updated=%s', created, updated)
    return created, updated
