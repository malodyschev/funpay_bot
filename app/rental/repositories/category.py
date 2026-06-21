from collections.abc import Sequence

import sqlalchemy as sa

from app.rental.common.enums import FulfillmentEnum, ProviderEnum
from app.rental.models.category import Category
from app.rental.repositories.base import Repository


class CategoryRepository(Repository[Category]):
    model = Category

    async def get_children(self, parent_id: int | None) -> Sequence[Category]:
        """Прямые дети узла (или корни при parent_id=None), в порядке меню."""
        condition = (
            Category.parent_id.is_(None)
            if parent_id is None
            else Category.parent_id == parent_id
        )
        query = (
            sa.select(Category)
            .where(condition)
            .order_by(Category.sort, Category.title)
        )
        return await self.scalars(query)

    async def resolve(
        self,
        category_id: int | None,
    ) -> tuple[FulfillmentEnum | None, ProviderEnum | None]:
        """Резолв (fulfillment, provider) с наследованием вверх по дереву.

        Поднимаемся от листа к корню, беря первый non-NULL для каждого поля.
        Дерево крошечное — грузим все категории разом и идём в памяти.
        """
        if category_id is None:
            return None, None
        cats = {c.id: c for c in await self.get_all()}
        fulfillment: FulfillmentEnum | None = None
        provider: ProviderEnum | None = None
        current = cats.get(category_id)
        seen: set[int] = set()
        while current is not None and current.id not in seen:
            seen.add(current.id)  # страховка от циклов в parent_id
            if fulfillment is None:
                fulfillment = current.fulfillment
            if provider is None:
                provider = current.provider
            current = cats.get(current.parent_id) if current.parent_id else None
        return fulfillment, provider
