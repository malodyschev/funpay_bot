import json
from dataclasses import dataclass

from app.rental.common.exceptions import SteamModuleError


@dataclass
class ParsedMaFile:
    """Данные, извлечённые из .maFile (формат SDA / steamguard-cli)."""

    account_name: str
    steam_id: str
    shared_secret: str
    identity_secret: str
    device_id: str | None
    revocation_code: str | None
    refresh_token: str | None


_REQUIRED = ('account_name', 'shared_secret', 'identity_secret')


def parse_mafile(raw: str | bytes) -> ParsedMaFile:
    """Распарсить содержимое .maFile в ParsedMaFile.

    Raises:
        SteamModuleError: если это не валидный maFile или нет обязательных полей.
    """
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SteamModuleError(f'не удалось прочитать maFile как JSON: {exc}') from exc

    if not isinstance(data, dict):
        raise SteamModuleError('maFile должен быть JSON-объектом')

    missing = [field for field in _REQUIRED if not data.get(field)]
    if missing:
        raise SteamModuleError(f'в maFile нет обязательных полей: {", ".join(missing)}')

    steam_id = data.get('steam_id') or _steam_id_from_tokens(data)
    if not steam_id:
        raise SteamModuleError('в maFile нет steam_id')

    tokens = data.get('tokens') or {}
    return ParsedMaFile(
        account_name=str(data['account_name']),
        steam_id=str(steam_id),
        shared_secret=str(data['shared_secret']),
        identity_secret=str(data['identity_secret']),
        device_id=data.get('device_id'),
        revocation_code=data.get('revocation_code'),
        refresh_token=tokens.get('refresh_token'),
    )


def _steam_id_from_tokens(data: dict[str, object]) -> str | None:
    """Некоторые maFile хранят steam_id только внутри Session — подстрахуемся."""
    session = data.get('Session')
    if isinstance(session, dict):
        value = session.get('SteamID')
        if value:
            return str(value)
    return None
