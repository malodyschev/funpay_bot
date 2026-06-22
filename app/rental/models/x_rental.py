from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import XRentalStatusEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class XRental(Base):
    """Аренда X: один арендатор занимает один слот на одном X-аккаунте.

    На одном аккаунте до `slots` активных аренд. `x_account_id` изменяемый —
    при замене слетевшего аккаунта аренды переносятся на новый (см.
    XRentalService.replace_account). funpay_order_id уникален (идемпотентность).
    """

    __tablename__ = 'x_rentals'

    id: Mapped[int] = mapped_column(primary_key=True)
    x_account_id: Mapped[int] = mapped_column(sa.ForeignKey('x_accounts.id'), index=True)
    lot_id: Mapped[int | None] = mapped_column(sa.ForeignKey('lots.id'))
    buyer_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    buyer_username: Mapped[str | None] = mapped_column(sa.Text)
    chat_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    funpay_order_id: Mapped[str] = mapped_column(sa.Text, unique=True)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    # Когда впервые запросили !x-code (= ~момент логина). Якорь для ручного
    # матчинга в session manager X + старт отсчёта срока. NULL — ещё не входил.
    code_requested_at: Mapped[datetime | None] = mapped_column(sa.DateTime)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    status: Mapped[XRentalStatusEnum] = mapped_column(
        EnumAsString(XRentalStatusEnum),
        default=XRentalStatusEnum.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
