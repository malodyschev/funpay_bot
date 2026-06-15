import base64
import hashlib
import hmac
import struct
import time


# Алфавит, которым Steam кодирует 5-значный Guard-код (не цифры!).
_STEAM_ALPHABET = '23456789BCDFGHJKMNPQRTVWXY'
_CODE_LENGTH = 5
_INTERVAL = 30


def generate_steam_code(shared_secret: str, timestamp: int | None = None) -> str:
    """Сгенерировать Steam Guard код из shared_secret (TOTP, без сети).

    Алгоритм идентичен мобильному автентификатору Steam: HMAC-SHA1 от
    номера 30-секундного интервала, динамическая выборка 4 байт и
    перекодировка в 5 символов стимовского алфавита.
    """
    if timestamp is None:
        timestamp = int(time.time())
    counter = timestamp // _INTERVAL
    key = base64.b64decode(shared_secret)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()

    start = digest[19] & 0x0F
    code_int = struct.unpack('>I', digest[start : start + 4])[0] & 0x7FFFFFFF

    code = ''
    for _ in range(_CODE_LENGTH):
        code += _STEAM_ALPHABET[code_int % len(_STEAM_ALPHABET)]
        code_int //= len(_STEAM_ALPHABET)
    return code
