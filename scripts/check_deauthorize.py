"""Живая проверка ПОЛНОГО механизма деавторизации (W3) на расходном аккаунте.

ВНИМАНИЕ: реально отзывает ВСЕ сессии аккаунта — тебя выкинет из Steam
везде (в браузере, клиенте). Аутентификатор (maFile/2FA) при этом остаётся,
повторный логин работает. Запускай только на тестовом аккаунте.

    python3 scripts/check_deauthorize.py

Печатает число сессий до и сколько отозвано.
"""

import asyncio
import getpass
import glob
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rental.steam.interface import SteamCredentials  # noqa: E402
from app.rental.steam.login import login_to_steam  # noqa: E402
from app.rental.steam.mafile import parse_mafile  # noqa: E402
from app.rental.steam.deauth import deauthorize_all_sessions, enumerate_sessions  # noqa: E402


def _find_mafile() -> str:
    files = glob.glob(os.path.expanduser('~/.config/steamguard-cli/maFiles/*.maFile'))
    if not files:
        sys.exit('не нашёл maFile')
    return files[0]


async def main() -> None:
    with open(_find_mafile(), encoding='utf-8') as fh:
        parsed = parse_mafile(fh.read())
    print(f'аккаунт: {parsed.account_name}')
    if input('отозвать ВСЕ сессии? выкинет везде [y/N]: ').strip().lower() != 'y':
        sys.exit('отмена')
    password = os.getenv('STEAM_TEST_PASSWORD') or getpass.getpass('пароль Steam: ')

    creds = SteamCredentials(
        login=parsed.account_name,
        password=password,
        shared_secret=parsed.shared_secret,
        identity_secret=parsed.identity_secret,
        steam_id=parsed.steam_id,
        device_id=parsed.device_id,
    )
    print('логинюсь...')
    session = await login_to_steam(creds)
    try:
        before = len(await enumerate_sessions(session))
        print(f'сессий до: {before}')
        revoked = await deauthorize_all_sessions(session, parsed.shared_secret)
        print(f'УСПЕХ ✅ отозвано сессий: {revoked}')
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())