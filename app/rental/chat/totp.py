"""Генерация TOTP-кода (RFC 6238) из 2FA-ключа — стандартный Google-Authenticator.

Chat (=ChatGPT/OpenAI) использует обычный TOTP, поэтому код считаем сами из base32-
секрета, без внешних либ и без обращения к API.
"""
import base64
import hashlib
import hmac
import struct
import time


def totp_now(secret_base32: str, *, digits: int = 6, period: int = 30) -> str:
    """Текущий TOTP-код по base32-секрету (digits знаков, окно period сек)."""
    key = _decode_base32(secret_base32)
    counter = int(time.time() // period)
    digest = hmac.new(key, struct.pack('>Q', counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack('>I', digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10 ** digits)).zfill(digits)


def _decode_base32(secret: str) -> bytes:
    cleaned = secret.strip().replace(' ', '').upper()
    cleaned += '=' * (-len(cleaned) % 8)  # дополняем паддинг до кратности 8
    return base64.b32decode(cleaned)
