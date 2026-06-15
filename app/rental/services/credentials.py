from app.crypto import decrypt
from app.rental.models.account import Account
from app.rental.steam.interface import SteamCredentials


def build_credentials(account: Account) -> SteamCredentials:
    """Decrypt an account's secrets into SteamCredentials."""
    return SteamCredentials(
        login=account.login,
        password=decrypt(account.password_enc),
        shared_secret=decrypt(account.shared_secret_enc),
        identity_secret=decrypt(account.identity_secret_enc),
        steam_id=account.steam_id,
        device_id=account.device_id,
    )
