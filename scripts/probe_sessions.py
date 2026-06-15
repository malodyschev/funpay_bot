"""Разведка механизма деавторизации (W3): перечислить активные сессии акка.

Не отзывает ничего! Только логинится и зовёт EnumerateTokens, чтобы увидеть
формат списка refresh-токенов (сессий) — по нему построим revoke.

    python3 scripts/probe_sessions.py
"""

import asyncio
import getpass
import glob
import json
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rental.steam.interface import SteamCredentials  # noqa: E402
from app.rental.steam.login import login_to_steam  # noqa: E402
from app.rental.steam.mafile import parse_mafile  # noqa: E402


_ENUMERATE = 'https://api.steampowered.com/IAuthenticationService/EnumerateTokens/v1/'


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
        print('EnumerateTokens...')
        resp = await session.client.post(
            _ENUMERATE,
            params={'access_token': session.access_token},
            data={'access_token': session.access_token},
        )
        print(f'  status={resp.status_code}')
        try:
            data = resp.json().get('response', {})
        except Exception:  # noqa: BLE001
            print('  не JSON, тело:', resp.text[:400])
            return
        tokens = data.get('refresh_tokens', [])
        print(f'  активных сессий: {len(tokens)}')
        for tok in tokens:
            safe = {
                k: tok.get(k)
                for k in ('token_id', 'token_description', 'time_updated', 'os_platform',
                          'auth_type', 'first_seen', 'last_seen')
            }
            print('  -', json.dumps(safe, ensure_ascii=False))
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())