from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.models.base_model import Base


class Lot(Base):
    """Лот FunPay и его параметры аренды."""

    __tablename__ = 'lots'

    id: Mapped[int] = mapped_column(primary_key=True)
    funpay_node_id: Mapped[int | None] = mapped_column(sa.Integer)
    title: Mapped[str] = mapped_column(sa.Text, unique=True)
    game: Mapped[str | None] = mapped_column(sa.Text)
    duration_minutes: Mapped[int] = mapped_column(sa.Integer)
    price: Mapped[float | None] = mapped_column(sa.Float)
    delivery_template: Mapped[str] = mapped_column(sa.Text)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
