from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import ExtensionReasonEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class Extension(Base):
    """Лог продлений аренды."""

    __tablename__ = 'extensions'

    id: Mapped[int] = mapped_column(primary_key=True)
    rental_id: Mapped[int] = mapped_column(sa.ForeignKey('rentals.id'))
    minutes_added: Mapped[int] = mapped_column(sa.Integer)
    reason: Mapped[ExtensionReasonEnum] = mapped_column(EnumAsString(ExtensionReasonEnum))
    # Заказ-продление FunPay (для идемпотентности); None для отзыва/ручного.
    funpay_order_id: Mapped[str | None] = mapped_column(sa.Text, unique=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
