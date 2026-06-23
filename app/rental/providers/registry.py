from app.rental.common.enums import ProviderEnum
from app.rental.providers.base import RentalProvider
from app.rental.providers.steam import SteamProvider
from app.runtime import RentalDeps


def get_provider(provider: ProviderEnum | None, deps: RentalDeps) -> RentalProvider:
    """Вернуть бэкенд аренды по провайдеру категории.

    provider=None (лот без категории / категория без провайдера) трактуем как
    Steam — это обратная совместимость со старыми лотами до введения категорий.

    Chat не использует паттерн провайдера: его аренда обслуживается
    ChatRentalService напрямую (см. new_order._handle_chat_order), а заказы Chat
    перехватываются до вызова get_provider. Если CHAT всё же дошёл сюда — это
    ошибка маршрутизации, бьём явно, чтобы не выдать молча Steam-логику.
    """
    if provider == ProviderEnum.CHAT:
        raise ValueError(
            'Chat-аренда не использует RentalProvider — она обслуживается '
            'ChatRentalService напрямую. get_provider не должен вызываться для Chat.',
        )
    return SteamProvider(deps)
