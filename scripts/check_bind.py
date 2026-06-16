"""Диагностика привязки аутентификатора на расходном аккаунте.

Показывает, что Steam отвечает на каждом шаге: какие подтверждения доступны
при логине и что возвращает AddAuthenticator (нужен ли телефон, шлёт ли код
активации). Секреты маскируются.

    python3 scripts/check_bind.py
"""

import asyncio
import getpass
import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.rental.steam.add_authenticator import (  # noqa: E402
    CODE_TYPE_DEVICE,
    CODE_TYPE_EMAIL,
    _TWO_FACTOR,
    _client,
    begin_credentials_login,
    poll_for_token,
    submit_code_and_get_token,
)
from app.rental.steam.confirmation import generate_device_id  # noqa: E402


_SECRET_KEYS = {'shared_secret', 'identity_secret', 'secret_1', 'uri', 'token_gid', 'access_token'}


async def main() -> None:
    login = input('Steam login: ').strip()
    password = os.getenv('STEAM_TEST_PASSWORD') or getpass.getpass('Steam password: ')
    proxy = get_settings().proxy_url or None

    print('\n[1] BeginAuthSession...')
    begin = await begin_credentials_login(login, password, proxy=proxy)
    types = begin['confirmation_types']
    print(f'    confirmation_types = {types}  (2=email-код, 3=код приложения, иначе=без guard)')

    if CODE_TYPE_DEVICE in types:
        print('    ⚠️ У аккаунта всё ещё активен мобильный аутентификатор (код приложения).')
        print('    Снятие не применилось или ещё в процессе. Привязать новый нельзя.')
        return

    if CODE_TYPE_EMAIL in types:
        print('    → нужен код входа с ПОЧТЫ. Проверь почту и СПАМ.')
        code = input('    введи код входа с почты: ').strip()
        access_token = await submit_code_and_get_token(
            client_id=begin['client_id'],
            request_id=begin['request_id'],
            steamid=begin['steamid'],
            code=code,
            code_type=CODE_TYPE_EMAIL,
            proxy=proxy,
        )
    else:
        print('    → Steam Guard не требуется, вхожу без кода.')
        access_token = await poll_for_token(
            client_id=begin['client_id'],
            request_id=begin['request_id'],
            proxy=proxy,
        )
    print('    access_token получен ✅')

    print('\n[2] AddAuthenticator...')
    device_id = generate_device_id(str(begin['steamid']))
    async with _client(proxy) as client:
        resp = await client.post(
            f'{_TWO_FACTOR}/AddAuthenticator/v1/',
            params={'access_token': access_token},
            data={
                'steamid': begin['steamid'],
                'authenticator_type': '1',
                'device_identifier': device_id,
                'sms_phone_id': '1',
                'version': '2',
            },
        )
    print(f'    http={resp.status_code} x-eresult={resp.headers.get("x-eresult")} '
          f'{resp.headers.get("x-error_message", "")}')
    data = resp.json().get('response', {})
    print(f'    status = {data.get("status")}  (1 = ок, аутентификатор создан)')
    for key, value in data.items():
        shown = f'<masked len={len(str(value))}>' if key in _SECRET_KEYS else value
        print(f'      {key}: {shown}')
    print('\nЕсли status=1 и есть shared_secret — Steam должен прислать код активации '
          '(на телефон или почту). Если status иной — смотри его и phone_number_hint.')


if __name__ == '__main__':
    asyncio.run(main())
