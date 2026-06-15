"""Разведка отзыва сессии (W3): найти рабочий вариант RevokeRefreshToken.

ОТЗЫВАЕТ ОДНУ сессию (по умолчанию старую безопасную — token_id из аргумента).
Пробует варианты авторизации по очереди и печатает eresult, чтобы понять,
нужен ли signature (shared_secret) или хватает access_token.

    python3 scripts/probe_revoke.py <token_id>

token_id бери из вывода probe_sessions.py (например старый KOMPUTER/DESKTOP).
"""

import asyncio
import base64
import getpass
import glob
import hashlib
import hmac
import os
import struct
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.rental.steam.interface import SteamCredentials  # noqa: E402
from app.rental.steam.login import login_to_steam  # noqa: E402
from app.rental.steam.mafile import parse_mafile  # noqa: E402


_REVOKE = 'https://api.steampowered.com/IAuthenticationService/RevokeRefreshToken/v1/'


def _find_mafile() -> str:
    files = glob.glob(os.path.expanduser('~/.config/steamguard-cli/maFiles/*.maFile'))
    if not files:
        sys.exit('не нашёл maFile')
    return files[0]


def _sig(secret: str, msg: bytes, algo: str) -> str:
    key = base64.b64decode(secret)
    return base64.b64encode(hmac.new(key, msg, algo).digest()).decode()


def _candidates(shared: str, identity: str, token_id: int, steamid: int) -> dict[str, str]:
    """Матрица гипотез подписи: алгоритм × ключ × порядок байт × состав сообщения."""
    out: dict[str, str] = {}
    for algo in ('sha1', 'sha256'):
        for kname, secret in (('shared', shared), ('identity', identity)):
            for endian in ('>', '<'):
                tid = struct.pack(endian + 'Q', token_id)
                sid = struct.pack(endian + 'Q', steamid)
                p = f'{algo}/{kname}/{endian}Q'
                out[f'{p}/token_id'] = _sig(secret, tid, algo)
                out[f'{p}/token_id+steamid'] = _sig(secret, tid + sid, algo)
            # token_id как ASCII-строка (без упаковки).
            out[f'{algo}/{kname}/str'] = _sig(secret, str(token_id).encode(), algo)
    return out


async def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('укажи token_id первым аргументом (из probe_sessions.py)')
    token_id = sys.argv[1]

    with open(_find_mafile(), encoding='utf-8') as fh:
        parsed = parse_mafile(fh.read())

    print(f'аккаунт: {parsed.account_name}, цель token_id={token_id}')
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
    cands = _candidates(
        parsed.shared_secret,
        parsed.identity_secret,
        int(token_id),
        int(parsed.steam_id),
    )

    base = {'access_token': session.access_token, 'token_id': token_id, 'steamid': parsed.steam_id}
    try:
        for name, sig in cands.items():
            data = {**base, 'signature': sig, 'revoke_action': '1'}
            resp = await session.client.post(
                _REVOKE,
                params={'access_token': session.access_token},
                data=data,
            )
            eresult = resp.headers.get('x-eresult', '?')
            errmsg = resp.headers.get('x-error_message', '')
            print(f'  [{name}] http={resp.status_code} eresult={eresult} {errmsg}')
            if eresult == '1':
                print(f'  ^ УСПЕХ — рабочая подпись: {name}')
                break
    finally:
        await session.close()


if __name__ == '__main__':
    asyncio.run(main())