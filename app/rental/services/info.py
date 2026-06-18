import math
from dataclasses import dataclass
from datetime import datetime
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import decrypt
from app.rental.common.commands import (
    EXTEND_TEXT,
    FAQ_TEXT,
    funpay_chat_url,
    funpay_lot_url,
)
from app.rental.common.enums import RentalStatusEnum
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.lot import LotRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.delivery import render_delivery
from app.runtime import RentalDeps


logger = getLogger(__name__)


@dataclass
class InfoService:
    """W6. Сервисные команды покупателя: !free, !acc, !code, !admin, !extend."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)
    lot_repo: ClassVar[LotRepository] = get_repository(LotRepository)

    async def send_credentials(self, chat_id: int) -> None:
        """!acc — повторно выдать логин/пароль активной аренды покупателю."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                chat_id,
                '🔑 Пока не вижу активной аренды на этом аккаунте.\n'
                'Команда !acc выдаёт логин и пароль уже после оплаты заказа.\n'
                'Если вы оплатили, а данные не пришли — напишите !admin, поможем.',
            )
            return
        account = await self.account_repo.get(rental.account_id)
        lot = await self.lot_repo.get_or_none(id_=rental.lot_id)
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        template = lot.delivery_template if lot else 'Логин: {login}\nПароль: {password}'
        text = render_delivery(
            template,
            login=account.login,
            password=decrypt(account.password_enc),
            minutes=minutes,
            game=(lot.game if lot else '') or '',
        )
        await self.deps.funpay.send_message(chat_id, text)

    async def call_admin(self, chat_id: int) -> None:
        """!admin — уведомить администратора, что покупателю нужна помощь."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if rental:
            who = f'покупатель {rental.buyer_username} (заказ {rental.funpay_order_id})'
        else:
            who = 'покупатель без активной аренды'
        await self.deps.notifier.notify(
            f'🆘 Вызов администратора в чат #{chat_id}: {who}.\n'
            f'Открыть чат: {funpay_chat_url(chat_id)}',
        )
        await self.deps.funpay.send_message(
            chat_id,
            '✅ Администратор уведомлён и скоро подключится. Спасибо за ожидание!',
        )

    async def request_refund(self, chat_id: int) -> None:
        """!refund — покупатель просит возврат → админу приходит запрос с Да/Нет."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                chat_id,
                '↩️ Активной аренды для возврата не вижу.\n'
                'Если оплатили только что и что-то не так — напишите !admin.',
            )
            return
        await self.deps.notifier.request_refund(
            rental.funpay_order_id,
            f'запрос покупателя {rental.buyer_username} по команде !refund',
        )
        await self.deps.funpay.send_message(
            chat_id,
            '↩️ Запрос на возврат отправлен продавцу. Дождитесь решения — '
            'ответ придёт сюда же.',
        )

    async def extend_info(self, chat_id: int) -> None:
        """!extend — ссылка на продление, но только если у покупателя есть активная аренда."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                chat_id,
                'У вас нет активной аренды для продления 🤷\n'
                'Чтобы арендовать — откройте лоты в профиле продавца и оформите заказ.',
            )
            return
        offer = await self._extension_offer()
        if offer is None:
            await self.deps.funpay.send_message(chat_id, EXTEND_TEXT)
            return
        link, minutes = offer
        await self.deps.funpay.send_message(
            chat_id,
            '♻️ Продлить аренду\n\n'
            f'Оплатите лот продления (+{minutes} мин) — время добавится '
            'автоматически к вашей текущей аренде:\n'
            f'{link}\n\n'
            f'💡 Нужно больше времени — возьмите несколько штук: 2 шт. = +{minutes * 2} мин.\n'
            'Остались вопросы — напишите !admin.',
        )

    async def _extension_offer(self) -> tuple[str, int] | None:
        """Ссылка на лот продления и сколько минут он добавляет (None, если не настроен)."""
        lot = await self.lot_repo.get_extension_lot()
        if lot and lot.funpay_lot_id:
            return funpay_lot_url(lot.funpay_lot_id), lot.duration_minutes
        return None

    async def time_left(self, chat_id: int) -> None:
        """!time — сколько осталось до конца аренды."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if not rental:
            await self.deps.funpay.send_message(
                chat_id,
                '⏳ Активной аренды не вижу. Время показывается после оплаты заказа.',
            )
            return
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        await self.deps.funpay.send_message(chat_id, f'⏳ До конца аренды осталось ~{minutes} мин.')

    async def stock(self, chat_id: int) -> None:
        """!free — наличие по лоту покупателя (который он смотрит или арендует).

        Лот определяем: по активной аренде → иначе по «Покупатель смотрит» на
        FunPay. Если лот определить не удалось — показываем наличие по всем лотам.
        """
        title = await self._target_lot_title(chat_id)
        if title is None:
            await self._send_all_stock(
                chat_id,
                header='🔍 Не понял, какой лот вас интересует. Наличие по всем лотам:',
            )
            return

        free = await self._free_by_title(title)
        if free > 0:
            body = f'✅ «{title}»: свободно аккаунтов — {free}. Можно брать!'
        else:
            body = (
                f'⛔ «{title}»: свободных аккаунтов сейчас нет.\n'
                'Загляните в другие лоты профиля или напишите !admin.'
            )
        await self.deps.funpay.send_message(
            chat_id,
            f'{body}\n\n🗂 !free-all — наличие по всем лотам.',
        )

    async def stock_all(self, chat_id: int) -> None:
        """!free-all — наличие по всем лотам аренды."""
        await self._send_all_stock(chat_id, header='🗂 Свободные аккаунты по всем лотам:')

    async def _target_lot_title(self, chat_id: int) -> str | None:
        """Название лота для !free: из активной аренды или из «Покупатель смотрит»."""
        rental = await self.rental_repo.get_active_by_chat(chat_id)
        if rental:
            lot = await self.lot_repo.get_or_none(id_=rental.lot_id)
            return lot.title if lot else None
        funpay_lot_id = await self.deps.funpay.get_viewed_lot_id(chat_id)
        if funpay_lot_id is None:
            return None
        lot = await self.lot_repo.get_or_none(funpay_lot_id=funpay_lot_id)
        return lot.title if lot else None

    async def _free_by_title(self, title: str) -> int:
        """Свободные аккаунты по всем активным офферам с этим названием.

        Несколько офферов могут называться одинаково и делить один пул — заказ
        матчится по названию, поэтому и наличие считаем по названию.
        """
        lots = await self.lot_repo.get_active_by_title(title)
        total = 0
        for lot in lots:
            if lot.is_extension:
                continue
            total += await self.account_repo.count_free(lot.id)
        return total

    async def _send_all_stock(self, chat_id: int, header: str) -> None:
        """Сводка наличия по всем лотам (агрегируем одинаковые названия)."""
        by_title: dict[str, int] = {}
        for lot, count in await self.lot_repo.free_account_counts():
            by_title[lot.title] = by_title.get(lot.title, 0) + count
        if not by_title:
            await self.deps.funpay.send_message(
                chat_id,
                'Лоты пока не настроены. Напишите !admin.',
            )
            return
        lines = [
            f'{"✅" if count > 0 else "⛔"} {title} — {count} шт.'
            for title, count in sorted(by_title.items())
        ]
        await self.deps.funpay.send_message(chat_id, header + '\n' + '\n'.join(lines))

    async def faq(self, chat_id: int) -> None:
        """Send the help message."""
        await self.deps.funpay.send_message(chat_id, FAQ_TEXT)

    async def warn_expiring(self, rental_id: int) -> None:
        """Pre-expiry warning job."""
        rental = await self.rental_repo.get_or_none(id_=rental_id)
        if not rental or rental.status != RentalStatusEnum.ACTIVE or rental.chat_id is None:
            return
        minutes = max(0, math.ceil((rental.expires_at - datetime.now()).total_seconds() / 60))
        text = (
            f'⏳ Аренда заканчивается через ~{minutes} мин. '
            'По истечении доступ закроется — сохраните прогресс.'
        )
        offer = await self._extension_offer()
        if offer is not None:
            link, added = offer
            text += f'\n\n♻️ Продлить (+{added} мин): {link}'
        await self.deps.funpay.send_message(rental.chat_id, text)
