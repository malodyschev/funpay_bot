import base64
import os
from dataclasses import dataclass, field
from logging import getLogger

import httpx
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from app.rental.common.exceptions import SteamModuleError
from app.rental.steam.interface import SteamCredentials
from app.rental.steam.totp import generate_steam_code


logger = getLogger(__name__)

_API = 'https://api.steampowered.com/IAuthenticationService'
_LOGIN = 'https://login.steampowered.com'
_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/120.0 Safari/537.36'
)
# Тип Steam Guard кода в новом auth-флоу: 3 = код мобильного автентификатора.
_CODE_TYPE_DEVICE = 3


@dataclass
class SteamSession:
    """Авторизованная web-сессия Steam.

    Держит httpx-клиент с cookie (steamLoginSecure на community/store/help),
    SteamID и токены. Через неё дальше дёргаем подтверждения и смену пароля.
    """

    client: httpx.AsyncClient
    steam_id: str
    access_token: str
    refresh_token: str
    session_id: str
    cookies: dict[str, str] = field(default_factory=dict)

    async def close(self) -> None:
        """Закрыть http-клиент сессии."""
        await self.client.aclose()


def _encrypt_password(password: str, mod_hex: str, exp_hex: str) -> str:
    """Зашифровать пароль публичным RSA-ключом Steam (PKCS1v15) → base64.

    Steam не принимает пароль в открытом виде: на шаге GetPasswordRSAPublicKey
    он отдаёт модуль и экспоненту, которыми мы и шифруем пароль перед отправкой.
    """
    public_numbers = rsa.RSAPublicNumbers(int(exp_hex, 16), int(mod_hex, 16))
    public_key = public_numbers.public_key()
    encrypted = public_key.encrypt(password.encode('ascii'), padding.PKCS1v15())
    return base64.b64encode(encrypted).decode()


async def _get_rsa_key(client: httpx.AsyncClient, login: str) -> tuple[str, str, str]:
    """Запросить у Steam публичный RSA-ключ для шифрования пароля."""
    resp = await client.get(
        f'{_API}/GetPasswordRSAPublicKey/v1/',
        params={'account_name': login},
    )
    data = resp.json().get('response', {})
    if not data.get('publickey_mod'):
        raise SteamModuleError('Steam не вернул RSA-ключ (проверь логин)')
    return data['publickey_mod'], data['publickey_exp'], data['timestamp']


async def _begin_auth(
    client: httpx.AsyncClient,
    login: str,
    encrypted_password: str,
    timestamp: str,
) -> dict:
    """Начать сессию авторизации по логину/паролю (шаг 1 нового флоу)."""
    resp = await client.post(
        f'{_API}/BeginAuthSessionViaCredentials/v1/',
        data={
            'account_name': login,
            'encrypted_password': encrypted_password,
            'encryption_timestamp': timestamp,
            'persistence': '1',
            'website_id': 'Community',
            'device_friendly_name': 'funpay-bot',
            'platform_type': '2',
        },
    )
    eresult = resp.headers.get('x-eresult')
    data = resp.json().get('response', {})
    if not data.get('client_id'):
        raise SteamModuleError(
            f'Steam отклонил логин/пароль (BeginAuthSession, eresult={eresult} '
            f'{resp.headers.get("x-error_message", "")})',
        )
    # Какие подтверждения Steam готов принять (3 = код мобильного аутентификатора).
    conf_types = {c.get('confirmation_type') for c in data.get('allowed_confirmations', [])}
    if conf_types and _CODE_TYPE_DEVICE not in conf_types:
        raise SteamModuleError(
            f'Steam не принимает код аутентификатора для этого входа: '
            f'allowed_confirmations={sorted(t for t in conf_types if t is not None)} '
            f'(2=email-код, 3=код приложения, 4=подтверждение в приложении). '
            f'Возможно, аккаунт требует подтверждение по email.',
        )
    return data


async def _submit_guard_code(
    client: httpx.AsyncClient,
    client_id: str,
    steam_id: str,
    code: str,
) -> None:
    """Отправить Steam Guard код (TOTP) для подтверждения входа (шаг 2)."""
    resp = await client.post(
        f'{_API}/UpdateAuthSessionWithSteamGuardCode/v1/',
        data={
            'client_id': client_id,
            'steamid': steam_id,
            'code': code,
            'code_type': str(_CODE_TYPE_DEVICE),
        },
    )
    eresult = resp.headers.get('x-eresult')
    if eresult not in (None, '1'):
        raise SteamModuleError(
            f'Steam отклонил Guard-код (eresult={eresult} '
            f'{resp.headers.get("x-error_message", "")}). '
            f'Проверь системное время (TOTP чувствителен к часам) и shared_secret.',
        )


async def _poll_tokens(client: httpx.AsyncClient, client_id: str, request_id: str) -> dict:
    """Опросить статус сессии и забрать access/refresh токены (шаг 3)."""
    resp = await client.post(
        f'{_API}/PollAuthSessionStatus/v1/',
        data={'client_id': client_id, 'request_id': request_id},
    )
    eresult = resp.headers.get('x-eresult')
    data = resp.json().get('response', {})
    if not data.get('refresh_token'):
        raise SteamModuleError(
            f'Steam не выдал токены (poll: eresult={eresult}, ответ={data}). '
            f'Обычно это неверный пароль либо неподтверждённый Guard-код.',
        )
    return data


async def _finalize_web_session(
    client: httpx.AsyncClient,
    steam_id: str,
    refresh_token: str,
    session_id: str,
) -> dict[str, str]:
    """Обменять refresh_token на web-cookie (steamLoginSecure) по доменам.

    Без этого шага мы залогинены «в API», но не в самом сайте — а флоу
    смены пароля и подтверждения идут именно через web (cookie-сессию).

    Важно: finalizelogin принимает только multipart/form-data и требует
    заголовки Origin/Referer от steamcommunity.com, иначе вернёт пустой
    transfer_info.
    """
    # Передаём поля как multipart/form-data (httpx делает это при files=...).
    resp = await client.post(
        f'{_LOGIN}/jwt/finalizelogin',
        files={
            'nonce': (None, refresh_token),
            'sessionid': (None, session_id),
            'redir': (None, 'https://steamcommunity.com/login/home/?goto='),
        },
        headers={
            'Origin': 'https://steamcommunity.com',
            'Referer': 'https://steamcommunity.com/',
        },
    )
    transfers = resp.json().get('transfer_info', [])
    if not transfers:
        raise SteamModuleError(
            f'Steam не вернул transfer_info. Ответ: {resp.status_code} {resp.text[:300]}',
        )

    cookies: dict[str, str] = {}
    for transfer in transfers:
        params = dict(transfer.get('params', {}))
        params['steamID'] = steam_id
        result = await client.post(transfer['url'], data=params)
        for name, value in result.cookies.items():
            cookies[name] = value
    return cookies


async def login_to_steam(
    credentials: SteamCredentials,
    *,
    proxy: str | None = None,
) -> SteamSession:
    """Залогиниться в Steam (логин + пароль + TOTP) и вернуть web-сессию.

    Полный новый auth-флоу Steam: RSA-шифрование пароля → старт сессии →
    подтверждение Guard-кодом из shared_secret → получение токенов →
    обмен на web-cookie. Полученную SteamSession используем для смены пароля.

    Raises:
        SteamModuleError: на любом шаге, если Steam отклонил вход.
    """
    if not credentials.steam_id:
        raise SteamModuleError('для логина нужен steam_id аккаунта')

    session_id = base64.b16encode(os.urandom(12)).decode().lower()
    client = httpx.AsyncClient(
        headers={'User-Agent': _USER_AGENT},
        timeout=20,
        follow_redirects=True,
        proxy=proxy,
    )
    # sessionid должен быть и cookie, и form-полем — иначе web-флоу не примет нас.
    for domain in ('steamcommunity.com', 'store.steampowered.com', 'help.steampowered.com'):
        client.cookies.set('sessionid', session_id, domain=domain)
    try:
        mod, exp, timestamp = await _get_rsa_key(client, credentials.login)
        encrypted = _encrypt_password(credentials.password, mod, exp)
        begin = await _begin_auth(client, credentials.login, encrypted, timestamp)

        code = generate_steam_code(credentials.shared_secret)
        await _submit_guard_code(client, begin['client_id'], credentials.steam_id, code)

        tokens = await _poll_tokens(client, begin['client_id'], begin['request_id'])
        cookies = await _finalize_web_session(
            client,
            credentials.steam_id,
            tokens['refresh_token'],
            session_id,
        )
    except httpx.HTTPError as exc:
        await client.aclose()
        raise SteamModuleError(f'сетевая ошибка при логине в Steam: {exc}') from exc
    except SteamModuleError:
        await client.aclose()
        raise

    logger.info('steam web session established for %s', credentials.login)
    return SteamSession(
        client=client,
        steam_id=credentials.steam_id,
        access_token=tokens['access_token'],
        refresh_token=tokens['refresh_token'],
        session_id=session_id,
        cookies=cookies,
    )
