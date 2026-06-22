from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.rental.common.enums import XRentalStatusEnum
from app.rental.models.lot import Lot
from app.rental.models.x_account import XAccount
from app.rental.models.x_rental import XRental
from app.rental.repositories.x_account import XAccountRepository
from app.rental.repositories.x_rental import XRentalRepository
from app.rental.services.base import get_repository
from app.rental.x.totp import totp_now
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class XPlaceResult:
    """Итог размещения заказа X в пуле."""

    account: XAccount | None
    rental: XRental | None
    reason: str  # ok | duplicate | no_pool | no_capacity


@dataclass
class XCodeResult:
    """Итог запроса кода (!x-code)."""

    code: str | None
    reason: str  # ok | expired | none | no_2fa


@dataclass
class XReplaceResult:
    """Итог замены слетевшего аккаунта."""

    ok: bool
    moved: int = 0
    reason: str = 'ok'  # ok | new_account_invalid | not_enough_slots


@dataclass
class XRentalService:
    """Мультитенантная аренда X: балансировка по слотам + жизненный цикл.

    Деавторизация ручная — сервис лишь отмечает истёкшие аренды (освобождая слот)
    и отдаёт алерты; код (!x-code) выдаётся, пока аренда активна.
    """

    session: AsyncSession
    deps: RentalDeps
    x_account_repo: ClassVar[XAccountRepository] = get_repository(XAccountRepository)
    x_rental_repo: ClassVar[XRentalRepository] = get_repository(XRentalRepository)

    async def place(
        self,
        lot: Lot,
        *,
        buyer_id: int,
        buyer_username: str | None,
        chat_id: int | None,
        order_id: str,
        amount: int = 1,
    ) -> XPlaceResult:
        """Подобрать наименее загруженный аккаунт пула и создать аренду."""
        existing = await self.x_rental_repo.get_by_order_id(order_id)
        if existing:
            account = await self.x_account_repo.get_or_none(id_=existing.x_account_id)
            return XPlaceResult(account, existing, 'duplicate')
        if lot.category_id is None:
            return XPlaceResult(None, None, 'no_pool')

        account = await self._pick_least_loaded(lot.category_id)
        if account is None:
            return XPlaceResult(None, None, 'no_capacity')

        minutes = lot.duration_minutes * max(1, amount)
        now = datetime.now()
        rental = await self.x_rental_repo.create({
            'x_account_id': account.id,
            'lot_id': lot.id,
            'buyer_id': buyer_id,
            'buyer_username': buyer_username,
            'chat_id': chat_id,
            'funpay_order_id': order_id,
            'started_at': now,
            'expires_at': now + timedelta(minutes=minutes),
            'status': XRentalStatusEnum.ACTIVE,
        })
        return XPlaceResult(account, rental, 'ok')

    async def _pick_least_loaded(self, category_id: int) -> XAccount | None:
        """Аккаунт пула с минимумом активных аренд среди тех, где есть свободный слот."""
        best: XAccount | None = None
        best_load: int | None = None
        for account in await self.x_account_repo.list_by_category(category_id):
            load = await self.x_rental_repo.count_active_by_account(account.id)
            if load < account.slots and (best_load is None or load < best_load):
                best, best_load = account, load
        return best

    async def code_for_chat(self, chat_id: int) -> XCodeResult:
        """TOTP-код активному арендатору (без лимита). Первый запрос = старт срока.

        На первом !x-code фиксируем `code_requested_at` (якорь логина для ручного
        матчинга в session manager) и пересчитываем `expires_at` от этого момента,
        сохраняя оплаченную длительность (= expires_at − started_at).
        """
        rental = await self.x_rental_repo.get_active_by_chat(chat_id)
        if rental and rental.expires_at > datetime.now():
            account = await self.x_account_repo.get_or_none(id_=rental.x_account_id)
            if not account or not account.totp_secret_enc:
                return XCodeResult(None, 'no_2fa')
            if rental.code_requested_at is None:
                now = datetime.now()
                duration = rental.expires_at - rental.started_at  # оплачено (с кол-вом)
                await self.x_rental_repo.update(
                    {'code_requested_at': now, 'expires_at': now + duration},
                    id_=rental.id,
                )
            return XCodeResult(totp_now(decrypt(account.totp_secret_enc)), 'ok')
        last = await self.x_rental_repo.get_or_none(chat_id=chat_id)
        return XCodeResult(None, 'expired' if last else 'none')

    async def expire_due(self) -> list[tuple[XRental, XAccount | None]]:
        """Отметить истёкшие аренды (освободив слот) и вернуть их для алертов."""
        due = list(await self.x_rental_repo.due(datetime.now()))
        alerts: list[tuple[XRental, XAccount | None]] = []
        for rental in due:
            await self.x_rental_repo.update(
                {'status': XRentalStatusEnum.EXPIRED}, id_=rental.id, commit=False,
            )
            account = await self.x_account_repo.get_or_none(id_=rental.x_account_id)
            alerts.append((rental, account))
        if due:
            await self.session.commit()
        return alerts

    async def kick(self, rental_id: int) -> bool:
        """Админ подтвердил кик → закрыть аренду (слот уже свободен с истечения)."""
        if not await self.x_rental_repo.get_or_none(id_=rental_id):
            return False
        await self.x_rental_repo.update(
            {'status': XRentalStatusEnum.CLOSED}, id_=rental_id,
        )
        return True

    async def replace_account(self, old_account_id: int, new_account_id: int) -> XReplaceResult:
        """Перенести все активные аренды слетевшего аккаунта на новый + уведомить."""
        new = await self.x_account_repo.get_or_none(id_=new_account_id)
        if not new or new.removed:
            return XReplaceResult(False, reason='new_account_invalid')

        active = list(await self.x_rental_repo.active_by_account(old_account_id))
        new_load = await self.x_rental_repo.count_active_by_account(new_account_id)
        if new.slots - new_load < len(active):
            return XReplaceResult(False, reason='not_enough_slots')

        for rental in active:
            await self.x_rental_repo.update(
                {'x_account_id': new_account_id}, id_=rental.id, commit=False,
            )
        await self.x_account_repo.update({'removed': True}, id_=old_account_id, commit=False)
        await self.session.commit()

        # Сменились login+password → шлём новые креды каждому арендатору.
        new_password = decrypt(new.password_enc)
        for rental in active:
            if rental.chat_id is not None:
                await self.deps.funpay.send_message(
                    rental.chat_id,
                    '🔄 Аккаунт заменён. Новые данные для входа:\n'
                    f'Логин: {new.login}\nПароль: {new_password}\n'
                    'Код входа — команда !x-code.',
                )
        logger.info('x replace %s -> %s: moved %s rentals', old_account_id,
                    new_account_id, len(active))
        return XReplaceResult(True, moved=len(active))
