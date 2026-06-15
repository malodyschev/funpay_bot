"""Живая проверка логина в Steam на расходном аккаунте.

Запуск (пароль спросит интерактивно, в историю не попадёт):
    python3 scripts/check_login.py

Или с явным путём к maFile:
    python3 scripts/check_login.py ~/.config/steamguard-cli/maFiles/xxx.maFile
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


def _find_mafile() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    pattern = os.path.expanduser('~/.config/steamguard-cli/maFiles/*.maFile')
    files = glob.glob(pattern)
    if not files:
        sys.exit(f'не нашёл maFile по {pattern} — укажи путь аргументом')
    return files[0]


async def main() -> None:
    path = _find_mafile()
    with open(path, encoding='utf-8') as fh:
        parsed = parse_mafile(fh.read())

    print(f'аккаунт: {parsed.account_name} (steam_id={parsed.steam_id})')
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
        print('УСПЕХ ✅ web-сессия получена')
        print('  steam_id   :', session.steam_id)
        print('  session_id :', session.session_id)
        print('  cookies    :', sorted(session.cookies.keys()))
        print('  access_token len :', len(session.access_token))
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())