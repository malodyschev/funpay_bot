from functools import lru_cache

from cryptography.fernet import Fernet

from app.config import get_settings


settings = get_settings()


@lru_cache
def _get_fernet() -> Fernet:
    """Собрать объект шифрования Fernet из ключа в настройках (ENCRYPTION_KEY)."""
    if not settings.encryption_key:
        raise RuntimeError('encryption_key is not set')
    return Fernet(settings.encryption_key.encode())


def encrypt(value: str) -> bytes:
    """Зашифровать строку (пароль/секрет) в байты для хранения в БД."""
    return _get_fernet().encrypt(value.encode())


def decrypt(value: bytes) -> str:
    """Расшифровать байты из БД обратно в исходную строку."""
    return _get_fernet().decrypt(value).decode()
