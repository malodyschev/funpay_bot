from dataclasses import dataclass
from typing import Any

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
    funpay_account: Any = None  # FunPayAPI.Account в боевом режиме (для синхронизации лотов)

    def get_deps(self) -> RentalDeps:
        if self.deps is None:
            raise RuntimeError('runtime deps are not initialized')
        return self.deps


runtime = _Runtime()
