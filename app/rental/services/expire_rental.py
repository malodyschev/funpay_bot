import asyncio
from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.rental.common.enums import (
    AccountStatusEnum,
    AccountTypeEnum,
    RentalStatusEnum,
)
from app.rental.models.account import Account
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.base import get_repository
from app.rental.services.credentials import build_credentials
from app.rental.services.lot_visibility import sync_lot_visibility
from app.runtime import RentalDeps


logger = getLogger(__name__)
settings = get_settings()

_EXPIRY_MESSAGE = (
    'Аренда окончена ⏳\n'
    'Доступ к аккаунту закрыт. Спасибо, что воспользовались услугой!\n'
    'Чтобы арендовать снова - оформите новый заказ.'
)


@dataclass
class ExpireRentalService:
    """W3. Истечение аренды → деавторизация сессий → возврат аккаунта в пул."""

    session: AsyncSession
    deps: RentalDeps
    rental_repo: ClassVar[RentalRepository] = get_repository(RentalRepository)
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)

    async def handle(self, rental_id: int) -> None:
        """End a rental: deauthorize sessions for online accounts, free the account."""
        rental = await self.rental_repo.get_or_none(id_=rental_id)
        processable = {RentalStatusEnum.ACTIVE, RentalStatusEnum.EXPIRING}
        if not rental or rental.status not in processable:
            logger.info('rental %s is not processable (status), skip expiry', rental_id)
            return

        account = await self.account_repo.get(rental.account_id)

        if account.type == AccountTypeEnum.OFFLINE:
            await self.account_repo.update({'status': AccountStatusEnum.FREE}, id_=account.id)
            await self.rental_repo.update({'status': RentalStatusEnum.EXPIRED}, id_=rental.id)
            await sync_lot_visibility(self.session, self.deps, account.lot_id)
            await self._notify_buyer(rental.chat_id)
            logger.info('offline rental %s expired, account %s freed', rental.id, account.id)
            return

        await self.account_repo.update(
            {'status': AccountStatusEnum.DEAUTHORIZING},
            id_=account.id,
        )

        if not await self._deauthorize_with_retries(account):
            await self.account_repo.update({'status': AccountStatusEnum.ERROR}, id_=account.id)
            await self.rental_repo.update({'status': RentalStatusEnum.ERROR}, id_=rental.id)
            await self.deps.notifier.notify(
                f'Не удалось деавторизовать аккаунт {account.login} (аренда {rental.id}). '
                f'Аккаунт переведён в ERROR, нужен ручной фикс.',
            )
            return

        await self.account_repo.update({'status': AccountStatusEnum.FREE}, id_=account.id)
        await self.rental_repo.update({'status': RentalStatusEnum.EXPIRED}, id_=rental.id)
        await sync_lot_visibility(self.session, self.deps, account.lot_id)
        await self._notify_buyer(rental.chat_id)
        logger.info(
            'rental %s expired, account %s sessions deauthorized and freed',
            rental.id,
            account.id,
        )

    async def _notify_buyer(self, chat_id: int | None) -> None:
        """Сообщить покупателю в чат FunPay, что аренда окончена."""
        if chat_id is None:
            return
        try:
            await self.deps.funpay.send_message(chat_id, _EXPIRY_MESSAGE)
        except Exception:
            logger.exception('failed to notify buyer about expiry (chat %s)', chat_id)

    async def _deauthorize_with_retries(self, account: Account) -> bool:
        """Try to deauthorize the account's sessions with exponential backoff."""
        credentials = build_credentials(account)
        delay = 2
        for attempt in range(1, settings.deauthorize_retries + 1):
            try:
                await self.deps.steam.deauthorize(credentials)
            except Exception:
                logger.warning(
                    'deauthorize failed for account %s (attempt %s/%s)',
                    account.id,
                    attempt,
                    settings.deauthorize_retries,
                    exc_info=True,
                )
                if attempt < settings.deauthorize_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
            else:
                return True
        return False
