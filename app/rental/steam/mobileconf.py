import time
from logging import getLogger

from app.rental.common.exceptions import SteamModuleError
from app.rental.steam.confirmation import generate_confirmation_key
from app.rental.steam.login import SteamSession


logger = getLogger(__name__)

_BASE = 'https://steamcommunity.com/mobileconf'

# Теги операций мобильных подтверждений (входят в ключ и в параметр запроса).
_TAG_LIST = 'list'  # получить список ожидающих подтверждений
_TAG_ACCEPT = 'accept'  # подтвердить (op=allow)


def _conf_params(
    session: SteamSession,
    identity_secret: str,
    device_id: str,
    tag: str,
) -> dict[str, str]:
    """Собрать общие query-параметры для запросов mobileconf.

    Steam ждёт device_id (p), steamid (a), ключ подтверждения под тег (k),
    время (t) и маркер мобильного клиента (m=react).
    """
    timestamp = int(time.time())
    return {
        'p': device_id,
        'a': session.steam_id,
        'k': generate_confirmation_key(identity_secret, tag, timestamp),
        't': str(timestamp),
        'm': 'react',
        'tag': tag,
    }


async def fetch_confirmations(
    session: SteamSession,
    identity_secret: str,
    device_id: str,
) -> list[dict]:
    """Получить список ожидающих мобильных подтверждений аккаунта.

    Это и проверка, что identity_secret + device_id + сессия рабочие:
    если ключ неверный — Steam вернёт success=false.
    """
    params = _conf_params(session, identity_secret, device_id, _TAG_LIST)
    resp = await session.client.get(f'{_BASE}/getlist', params=params)
    data = resp.json()
    if not data.get('success'):
        raise SteamModuleError(f'getlist отклонён Steam: {resp.status_code} {resp.text[:200]}')
    return data.get('conf', [])


async def accept_confirmation(
    session: SteamSession,
    identity_secret: str,
    device_id: str,
    confirmation_id: str,
    confirmation_nonce: str,
) -> bool:
    """Подтвердить одно действие (op=allow) — например, смену пароля.

    confirmation_id (cid) и confirmation_nonce (ck) берутся из элемента
    списка fetch_confirmations.
    """
    params = _conf_params(session, identity_secret, device_id, _TAG_ACCEPT)
    params.update(op='allow', cid=confirmation_id, ck=confirmation_nonce)
    resp = await session.client.get(f'{_BASE}/ajaxop', params=params)
    return bool(resp.json().get('success'))
