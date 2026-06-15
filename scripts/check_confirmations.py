"""Живая проверка мобильных подтверждений (mobileconf) на расходном аккаунте.

Логинится, запрашивает список подтверждений. Если Steam отвечает success
(пусть даже пустым списком) — значит identity_secret + device_id рабочие
и механизм подтверждений готов для смены пароля.

    python3 scripts/check_confirmations.py
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
from app.rental.steam.mobileconf import fetch_confirmations  # noqa: E402


def _find_mafile() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    files = glob.glob(os.path.expanduser('~/.config/steamguard-cli/maFiles/*.maFile'))
    if not files:
        sys.exit('не нашёл maFile — укажи путь аргументом')
    return files[0]


async def main() -> None:
    with open(_find_mafile(), encoding='utf-8') as fh:
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
        print('запрашиваю список подтверждений...')
        confs = await fetch_confirmations(session, parsed.identity_secret, parsed.device_id or '')
        print(f'УСПЕХ ✅ Steam принял ключ. Ожидающих подтверждений: {len(confs)}')
        for conf in confs:
            print('  -', {k: conf.get(k) for k in ('id', 'type', 'type_name', 'creator_id')})
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())