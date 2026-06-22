from app.rental.common.enums import ProviderEnum
from app.rental.providers.base import RentalProvider
from app.rental.providers.chat import ChatProvider
from app.rental.providers.steam import SteamProvider
from app.runtime import RentalDeps


def get_provider(provider: ProviderEnum | None, deps: RentalDeps) -> RentalProvider:
    """Вернуть бэкенд аренды по провайдеру категории.

    provider=None (лот без категории / категория без провайдера) трактуем как
    Steam — это обратная совместимость со старыми лотами до введения категорий.
    """
    if provider == ProviderEnum.CHAT:
        return ChatProvider()
    return SteamProvider(deps)
