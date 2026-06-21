from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.rental.common.enums import FulfillmentEnum, ProviderEnum
from app.rental.models.base_model import Base
from app.rental.models.type_decorators import EnumAsString


class Category(Base):
    """Узел дерева категорий (навигация админки + драйвер логики аренды).

    Дерево: parent_id=NULL — корень (Аренда / Автовыдача / Прочее). К листу
    привязываются лоты (Lot.category_id). `fulfillment` и `provider` задаются на
    ветке и наследуются вниз: лот резолвит их, поднимаясь к ближайшему non-NULL
    предку (см. CategoryRepository.resolve). Это и есть источник истины о том,
    какой логикой обрабатывать заказ и каким провайдером выдавать.
    """

    __tablename__ = 'categories'

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        sa.ForeignKey('categories.id'),
        index=True,
    )
    title: Mapped[str] = mapped_column(sa.Text)
    sort: Mapped[int] = mapped_column(sa.Integer, default=0)  # порядок в меню
    # NULL — наследуется от родителя (см. CategoryRepository.resolve).
    fulfillment: Mapped[FulfillmentEnum | None] = mapped_column(
        EnumAsString(FulfillmentEnum),
    )
    provider: Mapped[ProviderEnum | None] = mapped_column(EnumAsString(ProviderEnum))
    active: Mapped[bool] = mapped_column(sa.Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
