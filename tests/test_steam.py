import base64
import json

import pytest

from app.rental.common.exceptions import SteamModuleError
from app.rental.steam.confirmation import generate_confirmation_key, generate_device_id
from app.rental.steam.mafile import parse_mafile
from app.rental.steam.totp import generate_steam_code


_SECRET = base64.b64encode(b'0123456789abcdefghij').decode()


def test_totp_known_answer():
    # Зафиксированный вектор: вход -> выход не должен меняться при правках алгоритма.
    assert generate_steam_code(_SECRET, 1600000000) == '4M43X'
    assert generate_steam_code(_SECRET, 1600000030) == 'DJN63'


def test_totp_format():
    code = generate_steam_code(_SECRET, 1700000000)
    assert len(code) == 5
    assert all(c in '23456789BCDFGHJKMNPQRTVWXY' for c in code)


def test_totp_same_window_same_code():
    # Один и тот же 30-секундный слот -> одинаковый код.
    assert generate_steam_code(_SECRET, 1600000020) == generate_steam_code(_SECRET, 1600000049)


def test_parse_mafile_ok():
    raw = json.dumps({
        'account_name': 'resmp9ut',
        'steam_id': 76561198738546358,
        'shared_secret': _SECRET,
        'identity_secret': _SECRET,
        'device_id': 'android:abc',
        'revocation_code': 'R12345',
        'tokens': {'refresh_token': 'rt', 'access_token': 'at'},
    })
    parsed = parse_mafile(raw)
    assert parsed.account_name == 'resmp9ut'
    assert parsed.steam_id == '76561198738546358'
    assert parsed.device_id == 'android:abc'
    assert parsed.revocation_code == 'R12345'
    assert parsed.refresh_token == 'rt'


def test_parse_mafile_missing_fields():
    with pytest.raises(SteamModuleError):
        parse_mafile(json.dumps({'account_name': 'x'}))


def test_parse_mafile_not_json():
    with pytest.raises(SteamModuleError):
        parse_mafile('not a json')


def test_confirmation_key_known_answer():
    # Зафиксированный вектор: ключ зависит от тега операции и времени.
    assert generate_confirmation_key(_SECRET, 'conf', 1600000000) == '9Wz6g8k1ng4TDaT6zKN5hVm5Bc4='
    assert generate_confirmation_key(_SECRET, 'allow', 1600000000) == 'FWYIR0PfhCRxnDwOAsZKZVAAPDw='


def test_device_id_format():
    device_id = generate_device_id('76561198738546358')
    assert device_id.startswith('android:')
    assert len(device_id) == len('android:') + 36  # uuid с дефисами
