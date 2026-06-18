from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.models.base_model import Base


class Lot(Base):
    """Лот FunPay и его параметры аренды."""

    __tablename__ = 'lots'

    id: Mapped[int] = mapped_column(primary_key=True)
    funpay_node_id: Mapped[int | None] = mapped_column(sa.Integer)  # подкатегория FunPay
    funpay_lot_id: Mapped[int | None] = mapped_column(sa.Integer, unique=True)  # оффер FunPay
    # Название НЕ уникально: несколько офферов (=лотов) могут называться одинаково.
    title: Mapped[str] = mapped_column(sa.Text, index=True)
    game: Mapped[str | None] = mapped_column(sa.Text)
    duration_minutes: Mapped[int] = mapped_column(sa.Integer)
    price: Mapped[float | None] = mapped_column(sa.Float)
    delivery_template: Mapped[str] = mapped_column(sa.Text)
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    # Лот-продление: заказ добавляет время к активной аренде, не выдаёт аккаунт.
    is_extension: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # Лот автовыдачи (не аренда): бот его не обрабатывает, только помечает в админке.
    is_autodelivery: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    # Оффер удалён на FunPay — в админке не показываем (но запись храним ради истории).
    removed: Mapped[bool] = mapped_column(sa.Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
