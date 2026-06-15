import asyncio
from logging import getLogger

from app.config import get_settings
from app.database import get_session
from app.rental.repositories.rental import RentalRepository
from app.runtime import runtime


logger = getLogger(__name__)
settings = get_settings()

POLL_INTERVAL_SECONDS = 120


async def poll_once() -> None:
    """Один проход поллера: истечь просроченные аренды и разослать предупреждения.

    Источник истины — таблица rentals. Захват строк идёт через
    FOR UPDATE SKIP LOCKED, поэтому несколько инстансов не мешают друг другу.
    """
    from app.rental.services.expire_rental import ExpireRentalService
    from app.rental.services.info import InfoService

    deps = runtime.get_deps()

    async with get_session() as session:
        expire_ids = await RentalRepository(session).claim_due_for_expiry()
    for rental_id in expire_ids:
        async with get_session() as session:
            await ExpireRentalService(session, deps).handle(rental_id)
    if expire_ids:
        logger.info('poller processed %s expired rentals', len(expire_ids))

    async with get_session() as session:
        warn_ids = await RentalRepository(session).claim_due_for_warning(
            settings.warn_before_minutes,
        )
    for rental_id in warn_ids:
        async with get_session() as session:
            await InfoService(session, deps).warn_expiring(rental_id)
    if warn_ids:
        logger.info('poller sent %s expiry warnings', len(warn_ids))


async def run_poller() -> None:
    """Бесконечный цикл поллера (запускается фоновой задачей в run)."""
    logger.info('rental poller started (interval=%ss)', POLL_INTERVAL_SECONDS)
    while True:
        try:
            await poll_once()
        except Exception:
            logger.exception('rental poll iteration failed')
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
