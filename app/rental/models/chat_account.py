from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.models.base_model import Base


class ChatAccount(Base):
    """Шаренный Chat-аккаунт: его арендуют несколько человек одновременно.

    Привязан к КАТЕГОРИИ (пул): все лоты этой категории берут аккаунты отсюда.
    Вместимость — `slots` (балансировка least-loaded). Код входа — TOTP из
    `totp_secret_enc`. Деавторизация ручная. `removed` — аккаунт выведен из пула
    (слетел/заменён), записи аренд храним ради истории.
    """

    __tablename__ = 'chat_accounts'

    id: Mapped[int] = mapped_column(primary_key=True)
    category_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey('categories.id'),
        index=True,
    )
    login: Mapped[str] = mapped_column(sa.Text)
    password_enc: Mapped[bytes] = mapped_column(sa.LargeBinary)
    # 2FA-ключ (base32) для генерации TOTP-кода входа.
    totp_secret_enc: Mapped[bytes | None] = mapped_column(sa.LargeBinary)
    slots: Mapped[int] = mapped_column(sa.Integer, default=1)  # вместимость (напр. 50)
    removed: Mapped[bool] = mapped_column(sa.Boolean, default=False)  # выведен из пула
    notes: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
