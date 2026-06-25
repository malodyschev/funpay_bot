import contextlib
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from logging import getLogger
from operator import itemgetter
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.rental.chat.totp import totp_now
from app.rental.common.code_log import append_code_time
from app.rental.common.commands import BLOCKED_BUYER_MESSAGE
from app.rental.common.enums import ChatRentalStatusEnum
from app.rental.models.chat_account import ChatAccount
from app.rental.models.chat_rental import ChatRental
from app.rental.models.lot import Lot
from app.rental.repositories.blocked_buyer import BlockedBuyerRepository
from app.rental.repositories.chat_account import ChatAccountRepository
from app.rental.repositories.chat_rental import ChatRentalRepository
from app.rental.repositories.lot import LotRepository
from app.rental.services.base import get_repository
from app.runtime import RentalDeps


logger = getLogger(__name__)

CHAT_REVIEW_BONUS_MINUTES = 24 * 60  # +1 день за отзыв 5★ (как обещано в выдаче)
CHAT_WARN_BEFORE_MINUTES = 60  # за сколько до конца предупредить покупателя

CHAT_EXPIRY_MESSAGE = (
    '⏳ Ваша подписка закончилась.\n'
    'Спасибо, что были с нами! 🙌 Чтобы продолжить — оформите новый заказ, '
    'и мы сразу всё подключим.'
)


@dataclass
class ChatPlaceResult:
    """Итог размещения заказа Chat в пуле."""

    account: ChatAccount | None
    rental: ChatRental | None
    reason: str  # ok | duplicate | no_pool | no_capacity


@dataclass
class ChatCodeResult:
    """Итог запроса кода (!chat-code)."""

    code: str | None
    reason: str  # ok | expired | none | no_2fa


@dataclass
class ChatReplaceResult:
    """Итог замены слетевшего аккаунта."""

    ok: bool
    moved: int = 0
    reason: str = 'ok'  # ok | new_account_invalid | not_enough_slots


@dataclass
class ChatRentalService:
    """Мультитенантная аренда Chat: балансировка по слотам + жизненный цикл.

    Деавторизация ручная — сервис лишь отмечает истёкшие аренды (освобождая слот)
    и отдаёт алерты; код (!chat-code) выдаётся, пока аренда активна.
    """

    session: AsyncSession
    deps: RentalDeps
    chat_account_repo: ClassVar[ChatAccountRepository] = get_repository(ChatAccountRepository)
    chat_rental_repo: ClassVar[ChatRentalRepository] = get_repository(ChatRentalRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)
    blocked_repo: ClassVar[BlockedBuyerRepository] = get_repository(BlockedBuyerRepository)

    async def place(
        self,
        lot: Lot,
        *,
        buyer_id: int,
        buyer_username: str | None,
        chat_id: int | None,
        order_id: str,
        amount: int = 1,
    ) -> ChatPlaceResult:
        """Подобрать наименее загруженный аккаунт пула и создать аренду."""
        existing = await self.chat_rental_repo.get_by_order_id(order_id)
        if existing:
            account = await self.chat_account_repo.get_or_none(id_=existing.chat_account_id)
            return ChatPlaceResult(account, existing, 'duplicate')
        if lot.category_id is None:
            return ChatPlaceResult(None, None, 'no_pool')

        account = await self._pick_least_loaded(lot.category_id)
        if account is None:
            return ChatPlaceResult(None, None, 'no_capacity')

        minutes = lot.duration_minutes * max(1, amount)
        now = datetime.now()
        rental = await self.chat_rental_repo.create({
            'chat_account_id': account.id,
            'lot_id': lot.id,
            'buyer_id': buyer_id,
            'buyer_username': buyer_username,
            'chat_id': chat_id,
            'funpay_order_id': order_id,
            'started_at': now,
            'expires_at': now + timedelta(minutes=minutes),
            'status': ChatRentalStatusEnum.ACTIVE,
        })
        return ChatPlaceResult(account, rental, 'ok')

    async def _pick_least_loaded(self, category_id: int) -> ChatAccount | None:
        """Аккаунт пула с минимумом активных аренд и свободным слотом — с блокировкой.

        Кандидатов сортируем по загрузке, затем по одному БЛОКИРУЕМ строку
        (FOR UPDATE) и перепроверяем ёмкость под блокировкой — так два
        одновременных заказа не пересядут на один аккаунт и не превысят slots.
        Блокировка держится до commit аренды.
        """
        accounts = list(await self.chat_account_repo.list_by_category(category_id))
        ranked = sorted(
            accounts,
            key=lambda a: a.slots,  # стабильный обход; реальную загрузку проверим под локом
        )
        candidates: list[tuple[ChatAccount, int]] = []
        for account in ranked:
            load = await self.chat_rental_repo.count_active_by_account(account.id)
            if load < account.slots:
                candidates.append((account, load))
        candidates.sort(key=itemgetter(1))  # least-loaded первым
        for account, _ in candidates:
            locked = await self.chat_account_repo.lock(account.id)
            if locked is None:
                continue
            load = await self.chat_rental_repo.count_active_by_account(locked.id)
            if load < locked.slots:
                return locked  # лок держится до commit аренды
        return None

    async def code_for_chat(self, chat_id: int) -> ChatCodeResult:
        """TOTP-код активному арендатору (без лимита). Срок идёт с момента оплаты.

        На первом !chat-code фиксируем `code_requested_at` — якорь «когда вошёл» для
        ручного матчинга в session manager (срок при этом НЕ пересчитываем).
        """
        rental = await self.chat_rental_repo.get_active_by_chat(chat_id)
        if rental and rental.expires_at > datetime.now():
            if await self.blocked_repo.is_blocked(rental.buyer_username):
                return ChatCodeResult(None, 'blocked')
            account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
            if not account or not account.totp_secret_enc:
                return ChatCodeResult(None, 'no_2fa')
            # Фиксируем вход (запрос кода) в журнал аренды. Алерт не шлём — инфа нужна
            # при кике по истечении и в карточке аренды. code_requested_at = первый вход.
            now = datetime.now()
            values: dict = {'code_log': append_code_time(rental.code_log, now)}
            if rental.code_requested_at is None:
                values['code_requested_at'] = now
            await self.chat_rental_repo.update(values, id_=rental.id)
            return ChatCodeResult(totp_now(decrypt(account.totp_secret_enc)), 'ok')
        last = await self.chat_rental_repo.get_last_by_chat(chat_id)
        return ChatCodeResult(None, 'expired' if last else 'none')

    async def expire_due(self) -> list[tuple[ChatRental, ChatAccount | None]]:
        """Отметить истёкшие аренды (освободив слот) и вернуть их для алертов."""
        due = list(await self.chat_rental_repo.due(datetime.now()))
        alerts: list[tuple[ChatRental, ChatAccount | None]] = []
        for rental in due:
            await self.chat_rental_repo.update(
                {'status': ChatRentalStatusEnum.EXPIRED}, id_=rental.id, commit=False,
            )
            account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
            alerts.append((rental, account))
        if due:
            await self.session.commit()
            # Сообщаем покупателю, что подписка закончилась.
            for rental, _ in alerts:
                if rental.chat_id is not None:
                    await self.deps.funpay.send_message(rental.chat_id, CHAT_EXPIRY_MESSAGE)
            # Слоты освободились → показать лоты, если пул был заполнен.
            for category_id in {a.category_id for _, a in alerts if a and a.category_id}:
                await self.sync_pool_visibility(category_id)
        return alerts

    async def warn_due(self) -> int:
        """Предупредить покупателей, у кого аренда заканчивается в ближайший час."""
        rentals = await self.chat_rental_repo.claim_due_for_warning(CHAT_WARN_BEFORE_MINUTES)
        now = datetime.now()
        for rental in rentals:
            if rental.chat_id is None:
                continue
            minutes = max(0, math.ceil((rental.expires_at - now).total_seconds() / 60))
            await self.deps.funpay.send_message(
                rental.chat_id,
                f'⏳ Ваша подписка заканчивается через ~{minutes} мин.\n'
                'Хотите продолжить без перерыва — оформите новый заказ заранее. 😊',
            )
        return len(rentals)

    async def extend_for_review(self, chat_id: int) -> bool:
        """Продлить активную аренду на +1 день за отзыв 5★ (с дружелюбным сообщением)."""
        rental = await self.chat_rental_repo.get_active_by_chat(chat_id)
        if not rental:
            return False
        await self.chat_rental_repo.update(
            {'expires_at': rental.expires_at + timedelta(minutes=CHAT_REVIEW_BONUS_MINUTES)},
            id_=rental.id,
        )
        if rental.chat_id is not None:
            await self.deps.funpay.send_message(
                rental.chat_id,
                '🎉 Спасибо за отзыв! Дарим +1 день аренды 🎁\n'
                '⏳ Время уже добавлено к вашей подписке. Приятного пользования! ✨',
            )
        logger.info('chat rental %s extended for review (+%s min)', rental.id,
                    CHAT_REVIEW_BONUS_MINUTES)
        return True

    async def kick(self, rental_id: int) -> bool:
        """Админ подтвердил кик → закрыть аренду (слот уже свободен с истечения)."""
        if not await self.chat_rental_repo.get_or_none(id_=rental_id):
            return False
        await self.chat_rental_repo.update(
            {'status': ChatRentalStatusEnum.CLOSED}, id_=rental_id,
        )
        return True

    # ---------- команды покупателя (!time/!acc/!refund для Chat) ----------

    async def send_time_left(self, chat_id: int) -> bool:
        """!time — сколько осталось. True, если есть активная Chat-аренда."""
        rental = await self.chat_rental_repo.get_active_by_chat(chat_id)
        if not rental:
            return False
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        await self.deps.funpay.send_message(
            chat_id, f'⏳ До конца подписки осталось ~{minutes} мин.',
        )
        return True

    async def send_credentials(self, chat_id: int) -> bool:
        """!acc — повторно выдать логин/пароль активной Chat-аренды."""
        rental = await self.chat_rental_repo.get_active_by_chat(chat_id)
        if not rental:
            return False
        # Чёрный список — данные не выдаём (но аренда «наша», поэтому возвращаем True,
        # чтобы диспетчер не свалился в Steam-ветку !acc).
        if await self.blocked_repo.is_blocked(rental.buyer_username):
            await self.deps.funpay.send_message(chat_id, BLOCKED_BUYER_MESSAGE)
            return True
        account = await self.chat_account_repo.get_or_none(id_=rental.chat_account_id)
        if not account:
            return False
        await self.deps.funpay.send_message(
            chat_id,
            '🔐 Данные для входа\n'
            f'👤 Логин: {account.login}\n'
            f'🔑 Пароль: {decrypt(account.password_enc)}\n'
            '🔑 Код входа (2FA) — команда !chat-code',
        )
        return True

    async def request_refund(self, chat_id: int) -> bool:
        """!refund — покупатель просит возврат → админу запрос с Да/Нет."""
        rental = await self.chat_rental_repo.get_active_by_chat(chat_id)
        if not rental:
            return False
        await self.deps.notifier.request_refund(
            rental.funpay_order_id,
            f'запрос покупателя {rental.buyer_username} по команде !chat-refund',
        )
        await self.deps.funpay.send_message(
            chat_id,
            '↩️ Запрос на возврат отправлен продавцу. Дождитесь решения — ответ придёт сюда.',
        )
        return True

    async def sync_pool_visibility(self, category_id: int) -> None:
        """Скрыть Chat-лоты категории при заполнении пула, показать — при наличии мест."""
        accounts = await self.chat_account_repo.list_by_category(category_id)
        total_slots = sum(a.slots for a in accounts)
        used = await self.chat_rental_repo.count_active_in_category(category_id)
        free = total_slots - used
        hidden_any = False
        for lot in await self.lot_repo.list_by_category(category_id):
            if lot.funpay_lot_id is None:
                continue
            want_active = lot.active and free > 0
            try:
                await self.deps.funpay.set_lot_active(lot.funpay_lot_id, want_active)
            except Exception:
                logger.exception('chat pool visibility failed for lot %s', lot.id)
                continue
            if lot.active and not want_active:
                hidden_any = True
        if hidden_any and free <= 0:
            with contextlib.suppress(Exception):
                await self.deps.notifier.notify(
                    f'⚠️ Пул Chat (категория #{category_id}) заполнен — лоты скрыты на FunPay.',
                )

    async def replace_account(self, old_account_id: int, new_account_id: int) -> ChatReplaceResult:
        """Перенести все активные аренды слетевшего аккаунта на новый + уведомить."""
        new = await self.chat_account_repo.get_or_none(id_=new_account_id)
        if not new or new.removed:
            return ChatReplaceResult(False, reason='new_account_invalid')

        active = list(await self.chat_rental_repo.active_by_account(old_account_id))
        new_load = await self.chat_rental_repo.count_active_by_account(new_account_id)
        if new.slots - new_load < len(active):
            return ChatReplaceResult(False, reason='not_enough_slots')

        for rental in active:
            await self.chat_rental_repo.update(
                {'chat_account_id': new_account_id}, id_=rental.id, commit=False,
            )
        await self.chat_account_repo.update({'removed': True}, id_=old_account_id, commit=False)
        await self.session.commit()

        # Сменились login+password → шлём новые креды каждому арендатору.
        new_password = decrypt(new.password_enc)
        for rental in active:
            if rental.chat_id is not None:
                await self.deps.funpay.send_message(
                    rental.chat_id,
                    '🔄 Аккаунт заменён. Новые данные для входа:\n'
                    f'Логин: {new.login}\nПароль: {new_password}\n'
                    'Код входа — команда !chat-code.',
                )
        logger.info('chat replace %s -> %s: moved %s rentals', old_account_id,
                    new_account_id, len(active))
        return ChatReplaceResult(True, moved=len(active))
