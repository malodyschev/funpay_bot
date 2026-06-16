"""Диагностика: что реально отдаёт Runner.listen() на боевом аккаунте.

Включаем DEBUG библиотеки FunPayAPI, слушаем ~40 секунд и печатаем
каждое событие (тип + ключевые поля). Любые скрытые ошибки парсинга
(listen ловит их с ignore_exceptions=True) станут видны в логах.
"""
import logging
import time

import FunPayAPI
from FunPayAPI import Runner

from app.config import get_settings

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(name)s: %(message)s',
)

DURATION = 40


def main() -> None:
    s = get_settings()
    proxy = {'http': s.proxy_url, 'https': s.proxy_url} if s.proxy_url else None
    account = FunPayAPI.Account(
        s.funpay_golden_key,
        s.funpay_user_agent or None,
        requests_timeout=20,
        proxy=proxy,
    )
    account.get()
    print(f'>>> authorized as {account.username} (id={account.id})')

    runner = Runner(account, disable_message_requests=True)
    import threading
    threading.Thread(target=runner.loop, daemon=True).start()  # воркер очереди запросов
    print('>>> listening... купи лот / отправь сообщение в чат сейчас')
    start = time.time()
    for event in runner.listen(requests_delay=s.funpay_requests_delay):
        print(f'>>> EVENT {type(event).__name__}: {vars(event)!r}')
        if time.time() - start > DURATION:
            break
    print('>>> done')


if __name__ == '__main__':
    main()
