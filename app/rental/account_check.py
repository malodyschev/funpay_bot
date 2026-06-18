import asyncio
import contextlib
from datetime import datetime
from logging import getLogger

from app.database import get_session
from app.rental.common.enums import AccountStatusEnum
from app.rental.repositories.account import AccountRepository
from app.rental.services.credentials import build_credentials
from app.runtime import runtime


logger = getLogger(__name__)

CHECK_INTERVAL_SECONDS = 6 * 60 * 60  # проверяем аккаунты раз в 6 часов
_PAUSE_BETWEEN = 3  # пауза между аккаунтами, чтобы не долбить Steam


async def check_once() -> None:
    """Проверить логином все свободные аккаунты; битые → ERROR + алерт админу.

    Используем ТОЛЬКО логин (без отзыва сессий) — проверка не может никого
    выкинуть. И берём лишь FREE-аккаунты, перепроверяя статус прямо перед
    проверкой: если аккаунт за это время арендовали — пропускаем, чтобы не
    мешать играющему.
    """
    deps = runtime.get_deps()
    async with get_session() as session:
        account_ids = [a.id for a in await AccountRepository(session).list_free()]

    failed: list[str] = []
    for account_id in account_ids:
        # перепроверка перед логином: вдруг аккаунт уже арендован
        async with get_session() as session:
            account = await AccountRepository(session).get_or_none(id_=account_id)
        if not account or account.status != AccountStatusEnum.FREE:
            continue

        try:
            await deps.steam.login(build_credentials(account))
            ok = True
        except Exception as exc:
            ok = False
            logger.warning('account %s health check failed: %s', account.login, exc)

        async with get_session() as session:
            repo = AccountRepository(session)
            fresh = await repo.get_or_none(id_=account_id)
            if not fresh or fresh.status != AccountStatusEnum.FREE:
                continue  # успел уйти в аренду — не вмешиваемся
            data: dict = {'last_check': datetime.now()}
            if not ok:
                data['status'] = AccountStatusEnum.ERROR
                failed.append(fresh.login)
            await repo.update(data, id_=account_id)
        await asyncio.sleep(_PAUSE_BETWEEN)

    logger.info('account health check done: %s проверено, %s битых', len(account_ids), len(failed))
    if failed:
        with contextlib.suppress(Exception):
            await deps.notifier.notify(
                '⚠️ Проверка аккаунтов: не удалось войти в '
                + ', '.join(failed)
                + ' — помечены ERROR, нужен разбор.',
            )


async def run_account_check() -> None:
    """Бесконечный цикл проверки аккаунтов (первый прогон через интервал, не на старте)."""
    logger.info('account health checker started (interval=%ss)', CHECK_INTERVAL_SECONDS)
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        try:
            await check_once()
        except Exception:
            logger.exception('account check iteration failed')
