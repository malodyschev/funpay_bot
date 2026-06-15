import base64
import hashlib
import hmac
import struct
import time


# Тэги операций, под которые Steam просит отдельный ключ подтверждения.
# 'conf' — получить список подтверждений, 'allow' — подтвердить, 'cancel' — отклонить.
CONF_TAG_LIST = 'conf'
CONF_TAG_ACCEPT = 'allow'
CONF_TAG_CANCEL = 'cancel'


def generate_confirmation_key(identity_secret: str, tag: str, timestamp: int | None = None) -> str:
    """Сгенерировать ключ для мобильного подтверждения действия в Steam.

    Steam требует этот ключ (HMAC-SHA1 от времени + тега операции на
    identity_secret), чтобы подтвердить действие так же, как это делает
    мобильное приложение: список подтверждений, согласие, отмену.

    Args:
        identity_secret: identity_secret из maFile (base64).
        tag: тип операции — CONF_TAG_LIST / CONF_TAG_ACCEPT / CONF_TAG_CANCEL.
        timestamp: unix-время; по умолчанию текущее.

    Returns:
        Ключ подтверждения в base64 (его кладут в параметр запроса к Steam).
    """
    if timestamp is None:
        timestamp = int(time.time())
    secret = base64.b64decode(identity_secret)
    buffer = struct.pack('>Q', timestamp) + tag.encode('ascii')
    digest = hmac.new(secret, buffer, hashlib.sha1).digest()
    return base64.b64encode(digest).decode()


def generate_device_id(steam_id: str) -> str:
    """Собрать device_id из SteamID (запасной вариант, если его нет в maFile).

    Steam привязывает подтверждения к id «устройства». В maFile от
    steamguard-cli он уже есть, но на всякий случай умеем вывести его
    детерминированно из SteamID (sha1 → формат android:xxxxxxxx-...).
    """
    code = hashlib.sha1(steam_id.encode('ascii')).hexdigest()
    parts = [code[:8], code[8:12], code[12:16], code[16:20], code[20:32]]
    return 'android:' + '-'.join(parts)
