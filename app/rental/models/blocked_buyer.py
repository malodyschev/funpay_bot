from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.models.base_model import Base


class BlockedBuyer(Base):
    """Покупатель в чёрном списке: не продаём и не выдаём коды/данные.

    Матчинг по нику без регистра и без ведущего @ (username_norm). username хранит
    ник как ввёл админ — для отображения.
    """

    __tablename__ = 'blocked_buyers'

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.Text)
    username_norm: Mapped[str] = mapped_column(sa.Text, unique=True, index=True)
    note: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
