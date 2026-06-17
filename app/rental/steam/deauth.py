import base64
import hashlib
import hmac
from logging import getLogger

from app.rental.common.exceptions import SteamModuleError
from app.rental.steam.interface import SteamSessionInfo
from app.rental.steam.login import SteamSession


logger = getLogger(__name__)

_API = 'https://api.steampowered.com/IAuthenticationService'
_ENUMERATE = f'{_API}/EnumerateTokens/v1/'
_REVOKE = f'{_API}/RevokeRefreshToken/v1/'

# revoke_action=1 — пометить refresh-токен отозванным (сессия умирает).
_REVOKE_ACTION = '1'


def _revoke_signature(shared_secret: str, token_id: str) -> str:
    """Подпись для RevokeRefreshToken (как у мобильного аутентификатора).

    HMAC-SHA256 на ключе shared_secret, сообщение — token_id ASCII-строкой.
    Проверено на живом аккаунте: именно SHA256 и именно строка token_id
    (без упаковки в байты, без steamid). Иначе Steam вернёт AccessDenied.
    """
    key = base64.b64decode(shared_secret)
    digest = hmac.new(key, token_id.encode('ascii'), hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


async def enumerate_sessions(session: SteamSession) -> list[dict]:
    """Получить список активных сессий (refresh-токенов) аккаунта.

    Каждый элемент содержит token_id, token_description, last_seen и т.п.
    """
    resp = await session.client.post(
        _ENUMERATE,
        params={'access_token': session.access_token},
        data={'access_token': session.access_token},
    )
    if resp.status_code != 200:
        raise SteamModuleError(f'EnumerateTokens вернул {resp.status_code}: {resp.text[:200]}')
    return resp.json().get('response', {}).get('refresh_tokens', [])


async def list_account_sessions(session: SteamSession) -> list[SteamSessionInfo]:
    """Активные сессии аккаунта в удобном виде (для просмотра в админке)."""
    sessions = []
    for token in await enumerate_sessions(session):
        last_seen = token.get('last_seen') or {}
        sessions.append(SteamSessionInfo(
            description=token.get('token_description') or '—',
            last_seen_ts=last_seen.get('time'),
            country=last_seen.get('country'),
            city=last_seen.get('city'),
        ))
    return sessions


async def revoke_session(session: SteamSession, shared_secret: str, token_id: str) -> bool:
    """Отозвать одну сессию по token_id. True — успех (x-eresult=1)."""
    resp = await session.client.post(
        _REVOKE,
        params={'access_token': session.access_token},
        data={
            'access_token': session.access_token,
            'token_id': token_id,
            'steamid': session.steam_id,
            'revoke_action': _REVOKE_ACTION,
            'signature': _revoke_signature(shared_secret, token_id),
        },
    )
    eresult = resp.headers.get('x-eresult')
    if eresult != '1':
        logger.warning(
            'revoke token_id=%s отклонён: http=%s eresult=%s %s',
            token_id,
            resp.status_code,
            eresult,
            resp.headers.get('x-error_message', ''),
        )
    return eresult == '1'


async def deauthorize_all_sessions(session: SteamSession, shared_secret: str) -> int:
    """Отозвать ВСЕ сессии аккаунта — выгнать арендатора в конце аренды.

    Бьём все refresh-токены (включая наш текущий — сессия после этого не нужна).
    Отзыв сессий НЕ снимает аутентификатор, maFile/2FA остаются рабочими.

    Returns:
        Сколько сессий успешно отозвано.

    Raises:
        SteamModuleError: если не удалось получить список сессий.
    """
    tokens = await enumerate_sessions(session)
    revoked = 0
    for token in tokens:
        token_id = str(token.get('token_id', ''))
        if not token_id:
            continue
        if await revoke_session(session, shared_secret, token_id):
            revoked += 1
    logger.info(
        'deauthorized %s/%s sessions for steam_id=%s',
        revoked,
        len(tokens),
        session.steam_id,
    )
    return revoked
