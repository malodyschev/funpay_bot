from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import RentalStatusEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class Rental(Base):
    """Аренда аккаунта (активная или историческая)."""

    __tablename__ = 'rentals'
    __table_args__ = (sa.Index('ix_rentals_status_expires_at', 'status', 'expires_at'),)

    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(sa.ForeignKey('accounts.id'))
    lot_id: Mapped[int] = mapped_column(sa.ForeignKey('lots.id'))
    funpay_order_id: Mapped[str] = mapped_column(sa.Text, unique=True)
    buyer_id: Mapped[int | None] = mapped_column(sa.Integer)
    buyer_username: Mapped[str | None] = mapped_column(sa.Text)
    chat_id: Mapped[int | None] = mapped_column(sa.Integer)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime)
    status: Mapped[RentalStatusEnum] = mapped_column(
        EnumAsString(RentalStatusEnum),
        default=RentalStatusEnum.ACTIVE,
    )
    warned: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    extended_minutes: Mapped[int] = mapped_column(sa.Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
