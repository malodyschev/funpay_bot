import time
from logging import getLogger

import httpx

from app.rental.common.exceptions import SteamModuleError
from app.rental.steam.confirmation import generate_device_id
from app.rental.steam.login import (
    _API,
    _USER_AGENT,
    _encrypt_password,
    _get_rsa_key,
    _poll_tokens,
)
from app.rental.steam.totp import generate_steam_code


logger = getLogger(__name__)

_TWO_FACTOR = 'https://api.steampowered.com/ITwoFactorService'

# Типы Steam Guard подтверждения входа.
CODE_TYPE_EMAIL = 2  # код пришёл на почту
CODE_TYPE_DEVICE = 3  # код мобильного аутентификатора (значит он уже привязан)


def _client(proxy: str | None) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers={'User-Agent': _USER_AGENT},
        timeout=20,
        follow_redirects=True,
        proxy=proxy,
    )


async def begin_credentials_login(
    login: str,
    password: str,
    *,
    proxy: str | None = None,
) -> dict:
    """Шаг 1: вход по логину/паролю на аккаунт БЕЗ аутентификатора.

    Steam, увидев email-Steam Guard, сам отправит код на почту. Возвращаем
    идентификаторы сессии и доступные типы подтверждения.
    """
    async with _client(proxy) as client:
        mod, exp, timestamp = await _get_rsa_key(client, login)
        encrypted = _encrypt_password(password, mod, exp)
        resp = await client.post(
            f'{_API}/BeginAuthSessionViaCredentials/v1/',
            data={
                'account_name': login,
                'encrypted_password': encrypted,
                'encryption_timestamp': timestamp,
                'persistence': '1',
                'website_id': 'Community',
                'device_friendly_name': 'funpay-bot',
                'platform_type': '2',
            },
        )
        data = resp.json().get('response', {})
        if not data.get('client_id'):
            raise SteamModuleError(
                f'Steam отклонил логин/пароль (eresult={resp.headers.get("x-eresult")} '
                f'{resp.headers.get("x-error_message", "")})',
            )
        return {
            'client_id': data['client_id'],
            'request_id': data['request_id'],
            'steamid': data['steamid'],
            'confirmation_types': [
                c.get('confirmation_type') for c in data.get('allowed_confirmations', [])
            ],
        }


async def submit_code_and_get_token(
    *,
    client_id: str,
    request_id: str,
    steamid: str,
    code: str,
    code_type: int,
    proxy: str | None = None,
) -> str:
    """Шаг 2: отправить код входа (с почты) и забрать access_token."""
    async with _client(proxy) as client:
        resp = await client.post(
            f'{_API}/UpdateAuthSessionWithSteamGuardCode/v1/',
            data={
                'client_id': client_id,
                'steamid': steamid,
                'code': code,
                'code_type': str(code_type),
            },
        )
        eresult = resp.headers.get('x-eresult')
        if eresult not in (None, '1'):
            raise SteamModuleError(
                f'Steam отклонил код входа (eresult={eresult} '
                f'{resp.headers.get("x-error_message", "")})',
            )
        tokens = await _poll_tokens(client, client_id, request_id)
        return tokens['access_token']


async def poll_for_token(
    *,
    client_id: str,
    request_id: str,
    proxy: str | None = None,
) -> str:
    """Забрать access_token без ввода кода (аккаунт без Steam Guard)."""
    async with _client(proxy) as client:
        tokens = await _poll_tokens(client, client_id, request_id)
        return tokens['access_token']


async def add_authenticator(
    *,
    access_token: str,
    steamid: str,
    proxy: str | None = None,
) -> dict:
    """Шаг 3: попросить Steam создать аутентификатор.

    Возвращает секреты (shared_secret, identity_secret, revocation_code и т.д.).
    Steam отправит код активации (на телефон по SMS или на почту).
    """
    device_id = generate_device_id(str(steamid))
    async with _client(proxy) as client:
        resp = await client.post(
            f'{_TWO_FACTOR}/AddAuthenticator/v1/',
            params={'access_token': access_token},
            data={
                'steamid': steamid,
                'authenticator_type': '1',
                'device_identifier': device_id,
                'sms_phone_id': '1',
                'version': '2',
            },
        )
        data = resp.json().get('response', {})
        if not data.get('shared_secret'):
            raise SteamModuleError(
                f'AddAuthenticator не вернул секреты (status={data.get("status")}, '
                f'eresult={resp.headers.get("x-eresult")}). '
                f'Возможно, на аккаунте нет телефона и email-привязка недоступна.',
            )
        data['device_identifier'] = device_id
        return data


async def finalize_authenticator(
    *,
    access_token: str,
    steamid: str,
    shared_secret: str,
    activation_code: str,
    proxy: str | None = None,
) -> None:
    """Шаг 4: подтвердить привязку кодом активации + синхронизировать TOTP.

    Steam может ответить want_more — тогда подтверждаем кодом следующего
    30-секундного окна (так он убеждается, что мы умеем генерить коды).
    """
    async with _client(proxy) as client:
        base_time = int(time.time())
        for step in range(30):
            ts = base_time + step * 30
            resp = await client.post(
                f'{_TWO_FACTOR}/FinalizeAddAuthenticator/v1/',
                params={'access_token': access_token},
                data={
                    'steamid': steamid,
                    'authenticator_code': generate_steam_code(shared_secret, ts),
                    'authenticator_time': str(ts),
                    'activation_code': activation_code,
                    'validate_sms_code': '1',
                },
            )
            data = resp.json().get('response', {})
            if data.get('success'):
                return
            if data.get('want_more'):
                continue
            raise SteamModuleError(
                f'FinalizeAddAuthenticator не подтвердил привязку '
                f'(status={data.get("status")}, ответ={data}). Проверь код активации.',
            )
        raise SteamModuleError('FinalizeAddAuthenticator: не удалось синхронизировать коды')
