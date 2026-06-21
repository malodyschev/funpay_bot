from dataclasses import dataclass

from app.crypto import decrypt
from app.rental.models.account import Account
from app.rental.models.lot import Lot
from app.rental.providers.base import RentalProvider
from app.rental.services.credentials import build_credentials
from app.rental.services.delivery import render_delivery
from app.runtime import RentalDeps


@dataclass
class SteamProvider(RentalProvider):
    """Аренда Steam-аккаунтов: текущее боевое поведение, завёрнутое в провайдер."""

    deps: RentalDeps

    async def build_delivery_text(self, *, lot: Lot, account: Account, minutes: int) -> str:
        return render_delivery(
            lot.delivery_template,
            login=account.login,
            password=decrypt(account.password_enc),
            minutes=minutes,
            game=lot.game or '',
        )

    async def generate_code(self, account: Account) -> str:
        return await self.deps.steam.generate_code(build_credentials(account))

    async def deauthorize(self, account: Account) -> int:
        return await self.deps.steam.deauthorize(build_credentials(account))
