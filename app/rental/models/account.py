from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import AccountStatusEnum, AccountTypeEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class Account(Base):
    """Steam-аккаунт в пуле."""

    __tablename__ = 'accounts'
    __table_args__ = (sa.Index('ix_accounts_lot_id_status', 'lot_id', 'status'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    lot_id: Mapped[int] = mapped_column(sa.ForeignKey('lots.id'))
    login: Mapped[str] = mapped_column(sa.Text)
    password_enc: Mapped[bytes] = mapped_column(sa.LargeBinary)
    steam_id: Mapped[str | None] = mapped_column(sa.Text)
    shared_secret_enc: Mapped[bytes] = mapped_column(sa.LargeBinary)
    identity_secret_enc: Mapped[bytes] = mapped_column(sa.LargeBinary)
    revocation_code_enc: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    device_id: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[AccountStatusEnum] = mapped_column(
        EnumAsString(AccountStatusEnum),
        default=AccountStatusEnum.FREE,
    )
    type: Mapped[AccountTypeEnum] = mapped_column(
        EnumAsString(AccountTypeEnum),
        default=AccountTypeEnum.ONLINE,
    )
    notes: Mapped[str | None] = mapped_column(sa.Text)
    # Когда последний раз проверяли аккаунт логином (джоба раз в 6ч).
    last_check: Mapped[datetime | None] = mapped_column(sa.DateTime)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
