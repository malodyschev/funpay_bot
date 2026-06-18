from collections.abc import Sequence
from typing import Any, Generic, TypeVar

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import Select

from app.rental.common.exceptions import NotFoundException


TypeModel = TypeVar('TypeModel')


class Repository(Generic[TypeModel]):  # noqa: UP046
    """Base repository."""

    model: type[TypeModel] = None

    def __init__(self, session: AsyncSession):
        self.session = session

    @property
    def model_query(self) -> Select:
        return sa.select(self.model)

    async def execute(self, query, commit: bool = False):
        """Execute a query, optionally committing."""
        result = await self.session.execute(query)
        if commit:
            await self.session.commit()
        return result

    async def scalars(self, query) -> Sequence[TypeModel]:
        result = await self.execute(query)
        return result.scalars().all()

    async def scalar(self, query) -> TypeModel | None:
        result = await self.execute(query)
        return result.scalar_one_or_none()

    async def create(self, item: dict[str, Any], commit: bool = True) -> TypeModel:
        """Create object. commit=False — оставить в текущей транзакции (для атомарных операций)."""
        query = sa.insert(self.model).returning(self.model).values(**item)
        cursor = await self.execute(query, commit=commit)
        return cursor.scalar_one()

    async def update(
        self, item: dict[str, Any], id_: int | None = None, commit: bool = True, **filters,
    ) -> TypeModel:
        """Update object by id or filters. commit=False — не коммитить (атомарные операции)."""
        filters = self._get_filters(id_, **filters)
        query = sa.update(self.model).values(**item).returning(self.model).filter_by(**filters)
        cursor = await self.execute(query, commit=commit)
        return cursor.scalar_one()

    async def get(self, id_: int | None = None, **filters) -> TypeModel:
        """Get object by id or filters, raising if not found."""
        filters = self._get_filters(id_, **filters)
        res = await self.scalar(sa.select(self.model).filter_by(**filters))
        if not res:
            raise NotFoundException(detail=f'{self.model.__name__} is not found')
        return res

    async def get_or_none(self, id_: int | None = None, **filters) -> TypeModel | None:
        """Get object by id or filters, returning None if not found."""
        filters = self._get_filters(id_, **filters)
        return await self.scalar(sa.select(self.model).filter_by(**filters))

    async def get_all(self, **filters) -> Sequence[TypeModel]:
        """Get all objects, optionally filtered."""
        query = sa.select(self.model)
        if filters:
            query = query.filter_by(**filters)
        return await self.scalars(query)

    async def delete(self, id_: int) -> None:
        """Delete object by id."""
        await self.execute(sa.delete(self.model).where(self.model.id == id_), commit=True)

    async def commit(self) -> None:
        """Commit session."""
        await self.session.commit()

    @classmethod
    def _get_filters(cls, id_: int | None, **filters) -> dict:
        if id_:
            return {'id': id_}
        if not filters:
            raise NotFoundException(detail='No filters applied')
        return {**filters}
