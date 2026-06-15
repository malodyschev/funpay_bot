from dataclasses import dataclass
from logging import getLogger
from typing import ClassVar

from sqlalchemy.ext.asyncio import AsyncSession

from app.crypto import encrypt
from app.rental.common.enums import AccountStatusEnum, AccountTypeEnum
from app.rental.common.exceptions import DuplicateException
from app.rental.models.account import Account
from app.rental.repositories.account import AccountRepository
from app.rental.services.base import get_repository
from app.rental.steam.mafile import parse_mafile


logger = getLogger(__name__)


@dataclass
class AccountLoaderService:
    """Загрузка Steam-аккаунта в пул из .maFile (для админ-панели).

    maFile даёт логин и секреты (shared/identity/revocation), но НЕ пароль —
    пароль аккаунта админ передаёт отдельно. Все секреты шифруются (Fernet).
    """

    session: AsyncSession
    account_repo: ClassVar[AccountRepository] = get_repository(AccountRepository)

    async def load_from_mafile(
        self,
        *,
        raw_mafile: str | bytes,
        password: str,
        lot_id: int,
        account_type: AccountTypeEnum = AccountTypeEnum.ONLINE,
        login: str | None = None,
        notes: str | None = None,
    ) -> Account:
        """Создать Account из содержимого maFile + пароля."""
        parsed = parse_mafile(raw_mafile)
        return await self.create_account(
            lot_id=lot_id,
            login=login or parsed.account_name,
            password=password,
            steam_id=parsed.steam_id,
            shared_secret=parsed.shared_secret,
            identity_secret=parsed.identity_secret,
            revocation_code=parsed.revocation_code,
            device_id=parsed.device_id,
            account_type=account_type,
            notes=notes,
        )

    async def create_account(
        self,
        *,
        lot_id: int,
        login: str,
        password: str,
        steam_id: str | None,
        shared_secret: str,
        identity_secret: str,
        revocation_code: str | None,
        device_id: str | None,
        account_type: AccountTypeEnum = AccountTypeEnum.ONLINE,
        notes: str | None = None,
    ) -> Account:
        """Сохранить аккаунт из готовых секретов (maFile или авто-привязка).

        Все секреты шифруются Fernet. Дубль по steam_id запрещён.
        """
        if steam_id:
            existing = await self.account_repo.get_or_none(steam_id=steam_id)
            if existing:
                raise DuplicateException(
                    detail=f'аккаунт {steam_id} уже есть в пуле (id={existing.id})',
                )

        account = await self.account_repo.create({
            'lot_id': lot_id,
            'login': login,
            'password_enc': encrypt(password),
            'steam_id': steam_id,
            'shared_secret_enc': encrypt(shared_secret),
            'identity_secret_enc': encrypt(identity_secret),
            'revocation_code_enc': encrypt(revocation_code) if revocation_code else None,
            'device_id': device_id,
            'status': AccountStatusEnum.FREE,
            'type': account_type,
            'notes': notes,
        })
        logger.info('account %s (steam_id=%s) saved into pool', account.id, steam_id)
        return account
