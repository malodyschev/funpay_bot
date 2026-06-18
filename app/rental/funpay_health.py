import asyncio
import contextlib
from logging import getLogger

from app.runtime import runtime


logger = getLogger(__name__)

CHECK_INTERVAL_SECONDS = 300  # проверяем сессию FunPay раз в 5 минут
FAILS_TO_ALERT = 3            # ~15 минут подряд недоступности → алерт


async def run_funpay_health() -> None:
    """Следит за живостью сессии FunPay и алертит админа при падении.

    Раз в 5 минут дёргает account.get() (переавторизация/проверка сессии). N
    провалов подряд → один алерт «FunPay недоступен» (golden_key слетел/прокси
    лёг — заказы не принимаются). При восстановлении — уведомление об этом.
    """
    logger.info('funpay health watcher started (interval=%ss)', CHECK_INTERVAL_SECONDS)
    fails = 0
    alerted = False
    while True:
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
        account = runtime.funpay_account
        if account is None:
            continue
        try:
            await asyncio.to_thread(account.get)
        except Exception as exc:
            fails += 1
            logger.warning('funpay health check failed (%s подряд): %s', fails, exc)
            if fails >= FAILS_TO_ALERT and not alerted:
                alerted = True
                await _notify(
                    '⚠️ FunPay не отвечает: сессия слетела или golden_key протух '
                    '(проверь .env / прокси). Заказы сейчас НЕ принимаются.',
                )
        else:
            if alerted:
                await _notify('✅ FunPay снова на связи — приём заказов восстановлен.')
            fails = 0
            alerted = False


async def _notify(text: str) -> None:
    with contextlib.suppress(Exception):
        await runtime.get_deps().notifier.notify(text)
