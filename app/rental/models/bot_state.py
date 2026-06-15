import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.models.base_model import Base


class BotState(Base):
    """Служебное key-value состояние бота."""

    __tablename__ = 'bot_state'

    key: Mapped[str] = mapped_column(sa.Text, primary_key=True)
    value: Mapped[str | None] = mapped_column(sa.Text)
