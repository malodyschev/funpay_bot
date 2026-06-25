from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import ChatRentalStatusEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class ChatRental(Base):
    """Аренда Chat: один арендатор занимает один слот на одном Chat-аккаунте.

    На одном аккаунте до `slots` активных аренд. `chat_account_id` изменяемый —
    при замене слетевшего аккаунта аренды переносятся на новый (см.
    ChatRentalService.replace_account). funpay_order_id уникален (идемпотентность).
    """

    __tablename__ = 'chat_rentals'

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_account_id: Mapped[int] = mapped_column(sa.ForeignKey('chat_accounts.id'), index=True)
    lot_id: Mapped[int | None] = mapped_column(sa.ForeignKey('lots.id'))
    buyer_id: Mapped[int] = mapped_column(sa.BigInteger, index=True)
    buyer_username: Mapped[str | None] = mapped_column(sa.Text)
    chat_id: Mapped[int | None] = mapped_column(sa.BigInteger)
    funpay_order_id: Mapped[str] = mapped_column(sa.Text, unique=True)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    # Когда впервые запросили !chat-code (= ~момент логина). Якорь для ручного
    # матчинга в session manager Chat. NULL — ещё не входил.
    code_requested_at: Mapped[datetime | None] = mapped_column(sa.DateTime)
    # Все входы (= запросы кода) В ЭТОЙ аренде: ISO-таймстампы через перевод строки
    # (code_requested_at = первый вход; журнал — все входы). См. common.code_log.
    code_log: Mapped[str | None] = mapped_column(sa.Text)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime, index=True)
    warned: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # послали алерт «скоро конец»
    status: Mapped[ChatRentalStatusEnum] = mapped_column(
        EnumAsString(ChatRentalStatusEnum),
        default=ChatRentalStatusEnum.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
