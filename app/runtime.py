from dataclasses import dataclass

from app.rental.admin_bot.notifier import AdminNotifier
from app.rental.funpay.interface import FunPayConnector
from app.rental.steam.interface import SteamModule


@dataclass
class RentalDeps:
    """Внешние зависимости сервисного слоя (не привязаны к сессии БД)."""

    funpay: FunPayConnector
    steam: SteamModule
    notifier: AdminNotifier


@dataclass
class _Runtime:
    """Контейнер живых синглтонов, заполняется на старте приложения."""

    deps: RentalDeps | None = None

    def get_deps(self) -> RentalDeps:
        if self.deps is None:
            raise RuntimeError('runtime deps are not initialized')
        return self.deps


runtime = _Runtime()
