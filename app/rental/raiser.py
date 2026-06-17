import asyncio
from logging import getLogger

import FunPayAPI

from app.database import get_session
from app.rental.repositories.lot import LotRepository
from app.runtime import runtime


logger = getLogger(__name__)

RAISE_INTERVAL_SECONDS = 2 * 60 * 60  # пытаемся поднимать лоты раз в 2 часа


async def _our_category_ids(account: FunPayAPI.Account) -> set[int]:
    """ID игр (категорий), где есть наши привязанные лоты — по их подкатегориям.

    funpay_node_id у лота — это подкатегория; категорию (игру) достаём из дерева
    категорий, разобранного при account.get() на старте.
    """
    async with get_session() as session:
        lots = await LotRepository(session).active_linked()
    cats: set[int] = set()
    for node_id in {lot.funpay_node_id for lot in lots if lot.funpay_node_id}:
        sub = account.get_subcategory(FunPayAPI.enums.SubCategoryTypes.COMMON, node_id)
        if sub and sub.category:
            cats.add(sub.category.id)
    return cats


async def raise_once() -> None:
    """Поднять наши лоты во всех категориях, где они есть.

    Ошибки не критичны: FunPay часто отвечает «ещё рано» (RaiseError) или
    отдаёт сетевой сбой — просто логируем и пробуем в следующий заход.
    """
    account = runtime.funpay_account
    if account is None:
        return
    for cat_id in await _our_category_ids(account):
        try:
            wait = await asyncio.to_thread(account.raise_lots, cat_id)
            logger.info('raised lots in category %s (FunPay: next in ~%ss)', cat_id, wait)
        except Exception as exc:
            logger.info('raise category %s skipped (не критично): %s', cat_id, exc)


async def run_raiser() -> None:
    """Бесконечный цикл поднятия лотов (фоновая задача в run)."""
    logger.info('lot raiser started (interval=%ss)', RAISE_INTERVAL_SECONDS)
    while True:
        try:
            await raise_once()
        except Exception:
            logger.exception('raise iteration failed')
        await asyncio.sleep(RAISE_INTERVAL_SECONDS)
