from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from operator import itemgetter
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt, encrypt
from app.rental.chat.totp import totp_now
from app.rental.common.enums import (
    AccountStatusEnum,
    ExtensionReasonEnum,
    FulfillmentEnum,
    ProviderEnum,
    RentalStatusEnum,
)
from app.rental.models.account import Account
from app.rental.models.blocked_buyer import BlockedBuyer
from app.rental.models.category import Category
from app.rental.models.chat_account import ChatAccount
from app.rental.models.chat_rental import ChatRental
from app.rental.models.lot import Lot
from app.rental.models.rental import Rental
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.blocked_buyer import BlockedBuyerRepository, normalize_username
from app.rental.repositories.category import CategoryRepository
from app.rental.repositories.chat_account import ChatAccountRepository
from app.rental.repositories.chat_rental import ChatRentalRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.credentials import build_credentials
from app.rental.services.expire_rental import ExpireRentalService
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.lot_visibility import sync_lot_visibility
from app.rental.steam.interface import SteamSessionInfo
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class Dashboard:
    """Сводка для главного экрана админки."""

    status_counts: dict[AccountStatusEnum, int]
    active_rentals: int


@dataclass
class LotStock:
    """Лот + остаток аккаунтов (свободные / в аренде / всего)."""

    lot: Lot
    free: int
    total: int
    rented: int = 0


@dataclass
class CategoryBrowse:
    """Экран навигации по дереву категорий: узел + дети + лоты под ним.

    node=None — корень (Аренда / Автовыдача / Прочее). fulfillment/provider —
    резолв с наследованием от предков (драйвер логики и подсказка для кнопок).
    """

    node: Category | None
    children: list[Category]
    lots: list['LotStock']
    fulfillment: FulfillmentEnum | None
    provider: ProviderEnum | None
    uncategorized: int = 0  # лотов без категории (показываем бакет в корне)


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
class ChatRentalView:
    """Активная Chat-аренда с её аккаунтом пула и лотом."""

    rental: ChatRental
    account: ChatAccount | None
    lot: Lot | None


@dataclass
class RentalCounts:
    """Счётчики активных аренд по типам (для подменю «Активные аренды»)."""

    steam: int
    chat: int


@dataclass
class Credentials:
    """Раскрытые секреты аккаунта для админа (по кнопке)."""

    login: str
    password: str
    code: str


@dataclass
class ChatAccountLoad:
    """Chat-аккаунт пула + сколько слотов на нём занято (активные аренды)."""

    account: ChatAccount
    used: int

    @property
    def free(self) -> int:
        return max(0, self.account.slots - self.used)


@dataclass
class ChatPoolStat:
    """Сводка по пулу Chat одной категории (для дашборда)."""

    category_id: int
    title: str
    accounts: int  # сколько активных аккаунтов в пуле
    used: int      # занято слотов
    total: int     # всего слотов


@dataclass
class Stats:
    """Сводная статистика по арендам (для экрана статистики)."""

    rentals_24h: int
    rentals_7d: int
    rentals_30d: int
    active: int
    revenue_7d: float
    revenue_30d: float


@dataclass
class AdminService:
    """Чтение и ручные действия админки (переиспользует боевые сервисы)."""

    session: AsyncSession
    deps: RentalDeps
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)
    category_repo: ClassVar[CategoryRepository] = get_repository(CategoryRepository)
    chat_account_repo: ClassVar[ChatAccountRepository] = get_repository(ChatAccountRepository)
    chat_rental_repo: ClassVar[ChatRentalRepository] = get_repository(ChatRentalRepository)
    blocked_repo: ClassVar[BlockedBuyerRepository] = get_repository(BlockedBuyerRepository)

    # ---------- чёрный список покупателей ----------

    async def blocked_buyers(self) -> list[BlockedBuyer]:
        """Все ники в чёрном списке (по алфавиту)."""
        return list(await self.blocked_repo.list_all())

    async def add_blocked_buyer(self, username: str, note: str | None = None) -> bool:
        """Добавить ник в чёрный список. False — пусто или уже есть."""
        norm = normalize_username(username)
        if not norm:
            return False
        if await self.blocked_repo.get_by_username(username):
            return False
        await self.blocked_repo.create({
            'username': username.strip().lstrip('@'),
            'username_norm': norm,
            'note': (note or '').strip() or None,
        })
        return True

    async def remove_blocked_buyer(self, entry_id: int) -> None:
        """Убрать запись чёрного списка по id."""
        await self.blocked_repo.delete(entry_id)

    # ---------- чтение ----------

    async def browse(self, category_id: int | None) -> CategoryBrowse:
        """Содержимое узла дерева категорий: подкатегории + лоты с остатком."""
        node = await self.category_repo.get_or_none(id_=category_id) if category_id else None
        children = list(await self.category_repo.get_children(category_id))
        fulfillment, provider = await self.category_repo.resolve(category_id)
        lots: list[LotStock] = []
        if category_id is not None:
            for lot in await self.lot_repo.list_by_category(category_id):
                lots.append(await self._lot_stock(lot, provider))
        # «Неразобранные» (лоты без категории) показываем только в корне.
        uncategorized = await self.lot_repo.count_uncategorized() if category_id is None else 0
        return CategoryBrowse(
            node=node,
            children=children,
            lots=lots,
            fulfillment=fulfillment,
            provider=provider,
            uncategorized=uncategorized,
        )

    async def _lot_stock(self, lot: Lot, provider: ProviderEnum | None = None) -> LotStock:
        # Chat-лоты считаем по своему пулу (chat_accounts), а не по Steam-таблице accounts —
        # иначе они всегда «красные» (0 стока) и показывают чужие кнопки.
        if provider == ProviderEnum.CHAT:
            accounts = (
                await self.chat_account_repo.list_by_category(lot.category_id)
                if lot.category_id
                else []
            )
            total = len(accounts)
            return LotStock(lot=lot, free=total, total=total, rented=0)
        accounts = await self.account_repo.list_by_lot(lot.id)
        free = sum(1 for a in accounts if a.status == AccountStatusEnum.FREE)
        rented = sum(1 for a in accounts if a.status == AccountStatusEnum.RENTED)
        return LotStock(lot=lot, free=free, total=len(accounts), rented=rented)

    async def lot_provider(self, lot: Lot) -> ProviderEnum | None:
        """Провайдер лота (резолв по его категории)."""
        _, provider = await self.category_repo.resolve(lot.category_id)
        return provider

    async def create_category(self, parent_id: int | None, title: str) -> Category:
        """Создать подкатегорию (provider/fulfillment наследуются от родителя)."""
        return await self.category_repo.create({'title': title, 'parent_id': parent_id})

    async def uncategorized_lots(self) -> list[LotStock]:
        """Лоты без категории (синканные черновики) с остатком."""
        out: list[LotStock] = []
        for lot in await self.lot_repo.list_uncategorized():
            out.append(await self._lot_stock(lot))
        return out

    async def set_lot_category(self, lot_id: int, category_id: int) -> bool:
        """Привязать лот к категории-листу (для разбора синканных черновиков)."""
        if not await self.category_repo.get_or_none(id_=category_id):
            return False
        await self.lot_repo.update({'category_id': category_id}, id_=lot_id)
        return True

    async def category_paths(self) -> list[tuple[Category, str]]:
        """Все категории с полным путём («Аренда / Steam / Dota 2») для пикера."""
        cats = {c.id: c for c in await self.category_repo.get_all()}
        out: list[tuple[Category, str]] = []
        for category in cats.values():
            parts: list[str] = []
            current: Category | None = category
            seen: set[int] = set()
            while current is not None and current.id not in seen:
                seen.add(current.id)
                parts.append(current.title)
                current = cats.get(current.parent_id) if current.parent_id else None
            out.append((category, ' / '.join(reversed(parts))))
        out.sort(key=itemgetter(1))
        return out

    async def dashboard(self) -> Dashboard:
        """Счётчики по статусам аккаунтов + число активных аренд."""
        return Dashboard(
            status_counts=await self.account_repo.counts_by_status(),
            active_rentals=await self.rental_repo.count_active(),
        )

    async def stats(self) -> Stats:
        """Сводка по арендам за периоды + примерная выручка (по цене лотов)."""
        now = datetime.now()
        return Stats(
            rentals_24h=await self.rental_repo.count_since(now - timedelta(days=1)),
            rentals_7d=await self.rental_repo.count_since(now - timedelta(days=7)),
            rentals_30d=await self.rental_repo.count_since(now - timedelta(days=30)),
            active=await self.rental_repo.count_active(),
            revenue_7d=await self.rental_repo.revenue_since(now - timedelta(days=7)),
            revenue_30d=await self.rental_repo.revenue_since(now - timedelta(days=30)),
        )

    async def lots_with_stock(self) -> list[LotStock]:
        """Все лоты с остатком свободных аккаунтов (для дашборда)."""
        out: list[LotStock] = []
        for lot in await self.lot_repo.get_all():
            if lot.removed:
                continue  # удалён на FunPay — в админке не показываем
            out.append(await self._lot_stock(lot, await self.lot_provider(lot)))
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

    async def active_chat_rentals(self) -> list[ChatRentalView]:
        """Все активные Chat-аренды с аккаунтом пула и лотом."""
        rentals = await self.chat_rental_repo.get_active()
        out: list[ChatRentalView] = []
        for rental in rentals:
            account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
            lot = await self.lot_repo.get_or_none(id_=rental.lot_id) if rental.lot_id else None
            out.append(ChatRentalView(rental=rental, account=account, lot=lot))
        return out

    async def chat_rental_view(self, rental_id: int) -> ChatRentalView | None:
        """Одна Chat-аренда с аккаунтом и лотом (для карточки арендатора)."""
        rental = await self.chat_rental_repo.get_or_none(id_=rental_id)
        if not rental:
            return None
        account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
        lot = await self.lot_repo.get_or_none(id_=rental.lot_id) if rental.lot_id else None
        return ChatRentalView(rental=rental, account=account, lot=lot)

    async def rental_counts(self) -> RentalCounts:
        """Сколько активных аренд по типам (для подменю «Активные аренды»)."""
        return RentalCounts(
            steam=await self.rental_repo.count_active(),
            chat=await self.chat_rental_repo.count_active(),
        )

    async def reveal_credentials(self, account_id: int) -> Credentials | None:
        """Расшифровать креды аккаунта и сгенерировать текущий Guard-код."""
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return None
        creds = build_credentials(account)
        code = await self.deps.steam.generate_code(creds)
        return Credentials(login=creds.login, password=creds.password, code=code)

    async def list_sessions(self, account_id: int) -> list[SteamSessionInfo] | None:
        """Активные сессии Steam-аккаунта (логинится в Steam, может занять пару сек)."""
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return None
        return await self.deps.steam.list_sessions(build_credentials(account))

    # ---------- действия ----------

    async def kick(self, account_id: int) -> str:
        """Досрочно завершить аренду: деавторизация сессий + возврат в пул."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if not rental:
            return 'У аккаунта нет активной аренды.'
        await ExpireRentalService(self.session, self.deps).handle(rental.id)
        # Истечение могло упасть на деавторизации → аккаунт в ERROR (не освобождён).
        account = await self.account_repo.get_or_none(id_=account_id)
        if account and account.status == AccountStatusEnum.ERROR:
            return (
                '⚠️ Аренда закрыта, но ДЕАВТОРИЗАЦИЯ НЕ УДАЛАСЬ — аккаунт в ERROR, '
                'в пул не возвращён. Нужен ручной разбор (сессии могли остаться).'
            )
        return 'Аренда завершена досрочно, аккаунт деавторизован и возвращён в пул.'

    async def free_without_deauth(self, account_id: int) -> str:
        """Освободить аккаунт без деавторизации (вернуть в пул как есть)."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if rental:
            await self.rental_repo.update(
                {'status': RentalStatusEnum.EXPIRED}, id_=rental.id, commit=False,
            )
        await self.account_repo.update(
            {'status': AccountStatusEnum.FREE}, id_=account_id, commit=False,
        )
        await self.session.commit()
        await self._sync_visibility(account_id)
        return 'Аккаунт освобождён (без деавторизации).'

    async def set_status(self, account_id: int, status: AccountStatusEnum) -> str:
        """Сменить статус аккаунта (OFFLINE/BANNED/FREE). Активную аренду закрываем."""
        rental = await self.rental_repo.get_active_by_account(account_id)
        if rental and status != AccountStatusEnum.RENTED:
            await self.rental_repo.update(
                {'status': RentalStatusEnum.EXPIRED}, id_=rental.id, commit=False,
            )
        await self.account_repo.update({'status': status}, id_=account_id, commit=False)
        await self.session.commit()
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

    async def move_account_to_lot(self, account_id: int, target_lot_id: int) -> str:
        """Перенести аккаунт в другой лот (без отвязки аутентификатора).

        Нельзя двигать арендованный аккаунт (есть активная аренда на старом лоте).
        Обновляем видимость старого и нового лотов по стоку.
        """
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return 'Аккаунт не найден.'
        if account.status == AccountStatusEnum.RENTED:
            return 'Аккаунт в аренде — сначала заверши её.'
        old_lot_id = account.lot_id
        if old_lot_id == target_lot_id:
            return 'Аккаунт уже в этом лоте.'
        await self.account_repo.update({'lot_id': target_lot_id}, id_=account_id)
        await sync_lot_visibility(self.session, self.deps, old_lot_id)
        await sync_lot_visibility(self.session, self.deps, target_lot_id)
        return f'Аккаунт перемещён в лот #{target_lot_id}.'

    async def set_lot_duration(self, lot_id: int, minutes: int) -> str:
        """Задать длительность аренды лота (мин.)."""
        await self.lot_repo.update({'duration_minutes': minutes}, id_=lot_id)
        return f'Длительность лота: {minutes} мин.'

    async def toggle_lot_active(self, lot_id: int) -> bool | None:
        """Включить/выключить лот + показать/скрыть оффер на FunPay."""
        lot = await self.lot_repo.get_or_none(id_=lot_id)
        if not lot:
            return None
        new_active = not lot.active
        await self.lot_repo.update({'active': new_active}, id_=lot_id)
        await sync_lot_visibility(self.session, self.deps, lot_id)
        return new_active

    # Типы лота взаимоисключающие: аренда / продление / автовыдача.
    _LOT_TYPE_FLAGS: ClassVar[dict[str, tuple[bool, bool]]] = {
        'rental': (False, False),       # (is_extension, is_autodelivery)
        'extension': (True, False),
        'autodelivery': (False, True),
    }

    async def set_lot_type(self, lot_id: int, kind: str) -> bool:
        """Задать тип лота: 'rental' | 'extension' | 'autodelivery' (взаимоисключающе)."""
        is_ext, is_auto = self._LOT_TYPE_FLAGS[kind]
        if not await self.lot_repo.get_or_none(id_=lot_id):
            return False
        await self.lot_repo.update(
            {'is_extension': is_ext, 'is_autodelivery': is_auto},
            id_=lot_id,
        )
        await sync_lot_visibility(self.session, self.deps, lot_id)
        return True

    async def deauth_sessions(self, account_id: int) -> str:
        """Сбросить все Steam-сессии аккаунта (выкинуть всех), независимо от аренды."""
        account = await self.account_repo.get_or_none(id_=account_id)
        if not account:
            return 'Аккаунт не найден.'
        revoked = await self.deps.steam.deauthorize(build_credentials(account))
        return f'Сброшено сессий: {revoked}. Все, кто был залогинен, выкинуты из Steam.'

    async def create_lot(
        self,
        *,
        title: str,
        duration_minutes: int,
        template: str,
        game: str | None = None,
        price: float | None = None,
        is_extension: bool = False,
        category_id: int | None = None,
    ) -> Lot:
        """Создать новый лот аренды (или лот-продление, если is_extension)."""
        return await self.lot_repo.create({
            'title': title,
            'category_id': category_id,
            'game': game,
            'duration_minutes': duration_minutes,
            'price': price,
            'delivery_template': template,
            'active': True,
            'is_extension': is_extension,
        })

    # ---------- Chat-аккаунты (пул шаренной аренды) ----------

    async def chat_accounts_of_category(self, category_id: int) -> list[ChatAccount]:
        """Chat-аккаунты пула категории."""
        return list(await self.chat_account_repo.list_by_category(category_id))

    async def get_chat_account(self, chat_account_id: int) -> ChatAccount | None:
        return await self.chat_account_repo.get_or_none(id_=chat_account_id)

    async def create_chat_account(
        self,
        *,
        category_id: int,
        login: str,
        password: str,
        totp_secret: str | None,
        slots: int,
    ) -> ChatAccount:
        """Добавить Chat-аккаунт в пул категории (пароль и 2FA-ключ шифруются)."""
        return await self.chat_account_repo.create({
            'category_id': category_id,
            'login': login,
            'password_enc': encrypt(password),
            'totp_secret_enc': encrypt(totp_secret) if totp_secret else None,
            'slots': slots,
        })

    async def update_chat_account(
        self,
        chat_account_id: int,
        *,
        totp_secret: str | None = None,
        password: str | None = None,
        slots: int | None = None,
    ) -> bool:
        """Обновить 2FA-ключ / пароль / вместимость (переданные поля)."""
        if not await self.chat_account_repo.get_or_none(id_=chat_account_id):
            return False
        values: dict = {}
        if totp_secret is not None:
            values['totp_secret_enc'] = encrypt(totp_secret) if totp_secret else None
        if password is not None:
            values['password_enc'] = encrypt(password)
        if slots is not None:
            values['slots'] = slots
        if values:
            await self.chat_account_repo.update(values, id_=chat_account_id)
        return True

    async def delete_chat_account(self, chat_account_id: int) -> None:
        """Удалить Chat-аккаунт."""
        await self.chat_account_repo.delete(chat_account_id)

    async def chat_account_code(self, chat_account_id: int) -> str | None:
        """Текущий TOTP-код входа для Chat-аккаунта (для проверки 2FA-ключа)."""
        account = await self.get_chat_account(chat_account_id)
        if not account or not account.totp_secret_enc:
            return None
        return totp_now(decrypt(account.totp_secret_enc))

    async def chat_account_creds(self, chat_account_id: int) -> Credentials | None:
        """Полные креды Chat-аккаунта: логин(почта) + пароль + текущий TOTP-код."""
        account = await self.get_chat_account(chat_account_id)
        if not account:
            return None
        code = (
            totp_now(decrypt(account.totp_secret_enc))
            if account.totp_secret_enc
            else '— (нет 2FA)'
        )
        return Credentials(
            login=account.login,
            password=decrypt(account.password_enc),
            code=code,
        )

    async def chat_account_load(self, chat_account_id: int) -> int:
        """Сколько слотов занято на аккаунте (активные аренды)."""
        return await self.chat_rental_repo.count_active_by_account(chat_account_id)

    async def chat_pool_loads(self, category_id: int) -> list[ChatAccountLoad]:
        """Аккаунты пула категории с занятостью слотов (один запрос на загрузку)."""
        accounts = await self.chat_account_repo.list_by_category(category_id)
        loads = await self.chat_rental_repo.active_load_by_category(category_id)
        return [ChatAccountLoad(account=a, used=loads.get(a.id, 0)) for a in accounts]

    async def chat_pools(self) -> list[ChatPoolStat]:
        """Сводка по всем Chat-пулам: аккаунтов и занято/всего мест по категориям."""
        accounts = await self.chat_account_repo.list_all_active()
        by_category: dict[int, list[ChatAccount]] = {}
        for account in accounts:
            if account.category_id is None:
                continue
            by_category.setdefault(account.category_id, []).append(account)
        out: list[ChatPoolStat] = []
        for category_id, accs in by_category.items():
            category = await self.category_repo.get_or_none(id_=category_id)
            used = await self.chat_rental_repo.count_active_in_category(category_id)
            out.append(ChatPoolStat(
                category_id=category_id,
                title=category.title if category else f'#{category_id}',
                accounts=len(accs),
                used=used,
                total=sum(a.slots for a in accs),
            ))
        out.sort(key=lambda s: s.title)
        return out

    async def chat_replace_candidates(self, old_account_id: int) -> list[ChatAccount]:
        """Аккаунты пула, куда можно перенести аренды слетевшего (хватает слотов)."""
        old = await self.get_chat_account(old_account_id)
        if not old or old.category_id is None:
            return []
        need = await self.chat_rental_repo.count_active_by_account(old_account_id)
        out: list[ChatAccount] = []
        for account in await self.chat_account_repo.list_by_category(old.category_id):
            if account.id == old_account_id:
                continue
            free = account.slots - await self.chat_rental_repo.count_active_by_account(account.id)
            if free >= need:
                out.append(account)
        return out
