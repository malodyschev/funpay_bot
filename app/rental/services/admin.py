from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.enums import (
    AccountStatusEnum,
    ExtensionReasonEnum,
    RentalStatusEnum,
)
from app.rental.models.account import Account
from app.rental.models.lot import Lot
from app.rental.models.rental import Rental
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.credentials import build_credentials
from app.rental.services.expire_rental import ExpireRentalService
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.lot_visibility import sync_lot_visibility
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class Dashboard:
    """Сводка для главного экрана админки."""

    status_counts: dict[AccountStatusEnum, int]
    active_rentals: int


@dataclass
class LotStock:
    """Лот + сколько свободных аккаунтов."""

    lot: Lot
    free: int
    total: int


@dataclass
class AccountView:
    """Аккаунт с лотом и активной арендой (если есть) — для карточки/списка."""

    account: Account
    lot: Lot | None
    rental: Rental | None


@dataclass
class RentalView:
    """Активная аренда с аккаунтом и лотом."""

    rental: Rental
    account: Account | None
    lot: Lot | None


@dataclass
class Credentials:
    """Раскрытые секреты аккаунта для админа (по кнопке)."""

    login: str
    password: str
    code: str


@dataclass
class AdminService:
    """Чтение и ручные действия админки (переиспользует боевые сервисы)."""

    session: AsyncSession
    deps: RentalDeps
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)

    # ---------- чтение ----------

    async def dashboard(self) -> Dashboard:
        """Счётчики по статусам аккаунтов + число активных аренд."""
        return Dashboard(
            status_counts=await self.account_repo.counts_by_status(),
            active_rentals=await self.rental_repo.count_active(),
        )

    async def lots_with_stock(self) -> list[LotStock]:
        """Все лоты с остатком свободных аккаунтов."""
        lots = await self.lot_repo.get_all()
        out: list[LotStock] = []
        for lot in lots:
            accounts = await self.account_repo.list_by_lot(lot.id)
            free = sum(1 for a in accounts if a.status == AccountStatusEnum.FREE)
            out.append(LotStock(lot=lot, free=free, total=len(accounts)))
        return out

    async def get_lot(self, lot_id: int) -> Lot | None:
        """Лот по id."""
        return await self.lot_repo.get_or_none(id_=lot_id)

    async def accounts_of_lot(self, lot_id: int) -> list[AccountView]:
        """Аккаунты лота с активной арендой каждого (если есть)."""
        lot = await self.lot_repo.get_or_none(id_=lot_id)
        accounts = await self.account_repo.list_by_lot(lot_id)
        out: list[AccountView] = []
        for account in accounts:
            rental = None
            if account.status == AccountStatusEnum.RENTED:
                rental = await self.rental_repo.get_active_by_account(account.id)
            out.append(AccountView(account=account, lot=lot, rental=rental))
        return out

    async def account_card(self, account_id: int) -> AccountView | None:
        """Карточка одного аккаунта."""
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return None
        lot = await self.lot_repo.get_or_none(id_=account.lot_id)
        rental = await self.rental_repo.get_active_by_account(account.id)
        return AccountView(account=account, lot=lot, rental=rental)

    async def active_rentals(self) -> list[RentalView]:
        """Все активные аренды с аккаунтом и лотом."""
        rentals = await self.rental_repo.get_active()
        out: list[RentalView] = []
        for rental in rentals:
            account = await self.account_repo.get_or_none(id_=rental.account_id)
            lot = await self.lot_repo.get_or_none(id_=rental.lot_id)
            out.append(RentalView(rental=rental, account=account, lot=lot))
        return out

    async def reveal_credentials(self, account_id: int) -> Credentials | None:
        """Расшифровать креды аккаунта и сгенерировать текущий Guard-код."""
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return None
        creds = build_credentials(account)
        code = await self.deps.steam.generate_code(creds)
        return Credentials(login=creds.login, password=creds.password, code=code)

    # ---------- действия ----------

    async def kick(self, account_id: int) -> str:
        """Досрочно завершить аренду: деавторизация сессий + возврат в пул."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if not rental:
            return 'У аккаунта нет активной аренды.'
        await ExpireRentalService(self.session, self.deps).handle(rental.id)
        return 'Аренда завершена досрочно, аккаунт деавторизован и возвращён в пул.'

    async def free_without_deauth(self, account_id: int) -> str:
        """Освободить аккаунт без деавторизации (вернуть в пул как есть)."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if rental:
            await self.rental_repo.update({'status': RentalStatusEnum.EXPIRED}, id_=rental.id)
        await self.account_repo.update({'status': AccountStatusEnum.FREE}, id_=account_id)
        await self._sync_visibility(account_id)
        return 'Аккаунт освобождён (без деавторизации).'

    async def set_status(self, account_id: int, status: AccountStatusEnum) -> str:
        """Сменить статус аккаунта (OFFLINE/BANNED/FREE). Активную аренду закрываем."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if rental and status != AccountStatusEnum.RENTED:
            await self.rental_repo.update({'status': RentalStatusEnum.EXPIRED}, id_=rental.id)
        await self.account_repo.update({'status': status}, id_=account_id)
        await self._sync_visibility(account_id)
        return f'Статус аккаунта изменён на {status.name}.'

    async def _sync_visibility(self, account_id: int) -> None:
        account = await self.account_repo.get_or_none(id_=account_id)
        if account:
            await sync_lot_visibility(self.session, self.deps, account.lot_id)

    async def extend(self, account_id: int, minutes: int) -> str:
        """Продлить активную аренду аккаунта на N минут."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if not rental:
            return 'У аккаунта нет активной аренды.'
        await ExtendRentalService(self.session, self.deps).extend_by_id(
            rental.id,
            minutes,
            ExtensionReasonEnum.MANUAL,
        )
        return f'Аренда продлена на {minutes} мин.'

    async def set_notes(self, account_id: int, notes: str) -> str:
        """Записать заметку к аккаунту."""
        await self.account_repo.update({'notes': notes}, id_=account_id)
        return 'Заметка сохранена.'

    async def set_lot_duration(self, lot_id: int, minutes: int) -> str:
        """Задать длительность аренды лота (мин.)."""
        await self.lot_repo.update({'duration_minutes': minutes}, id_=lot_id)
        return f'Длительность лота: {minutes} мин.'

    async def toggle_lot_active(self, lot_id: int) -> bool | None:
        """Включить/выключить лот. Возвращает новое значение active (или None)."""
        lot = await self.lot_repo.get_or_none(id_=lot_id)
        if not lot:
            return None
        new_active = not lot.active
        await self.lot_repo.update({'active': new_active}, id_=lot_id)
        return new_active

    async def create_lot(
        self,
        *,
        title: str,
        duration_minutes: int,
        template: str,
        game: str | None = None,
        price: float | None = None,
        is_extension: bool = False,
    ) -> Lot:
        """Создать новый лот аренды (или лот-продление, если is_extension)."""
        return await self.lot_repo.create({
            'title': title,
            'game': game,
            'duration_minutes': duration_minutes,
            'price': price,
            'delivery_template': template,
            'active': True,
            'is_extension': is_extension,
        })
