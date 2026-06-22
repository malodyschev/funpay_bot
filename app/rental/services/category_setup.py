"""Сид базового дерева категорий + бэкфилл существующих лотов (идемпотентно).

Используется и в dev (`sync-schema`), и явной командой `backfill-categories`, и
безопасно гоняется повторно: трогает только лоты с category_id IS NULL. На проде
то же делает alembic-миграция c3d4e5f6a7b8 — эта функция нужна, чтобы «катнул и
подтянулось» работало независимо от пути накатки.
"""
from dataclasses import dataclass
from logging import getLogger

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from app.rental.common.enums import FulfillmentEnum, ProviderEnum
from app.rental.models.category import Category
from app.rental.models.lot import Lot
from app.rental.repositories.category import CategoryRepository


logger = getLogger(__name__)


@dataclass
class BackfillResult:
    skeleton_created: bool = False
    games_created: int = 0
    lots_backfilled: int = 0

    def summary(self) -> str:
        return (
            f'skeleton={"yes" if self.skeleton_created else "no"} '
            f'games_created={self.games_created} lots_backfilled={self.lots_backfilled}'
        )


async def seed_and_backfill(session: AsyncSession) -> BackfillResult:
    """Создать скелет дерева (если пусто) и развесить лоты без категории."""
    repo = CategoryRepository(session)
    result = BackfillResult()

    cats = list(await repo.get_all())
    if not cats:
        await _create_skeleton(session)
        cats = list(await repo.get_all())
        result.skeleton_created = True

    steam = next((c for c in cats if c.provider == ProviderEnum.STEAM), None)
    auto = next(
        (c for c in cats if c.fulfillment == FulfillmentEnum.AUTODELIVERY and c.parent_id is None),
        None,
    )
    if steam is None or auto is None:
        logger.warning('category skeleton incomplete (steam/auto not found), skip backfill')
        return result

    # Подкатегории-игры под Steam: по имени (без регистра), создаём недостающие.
    games = {c.title.casefold(): c for c in cats if c.parent_id == steam.id}

    null_lots = await session.scalars(
        sa.select(Lot).where(Lot.category_id.is_(None), Lot.removed.is_(False)),
    )
    for lot in null_lots:
        if lot.is_autodelivery:
            lot.category_id = auto.id
        elif lot.game:
            key = lot.game.casefold()
            game_cat = games.get(key)
            if game_cat is None:
                game_cat = await repo.create(
                    {'title': lot.game, 'parent_id': steam.id}, commit=False,
                )
                games[key] = game_cat
                result.games_created += 1
            lot.category_id = game_cat.id
        else:
            lot.category_id = steam.id  # аренда без игры (в т.ч. продления) → прямо в Steam
        result.lots_backfilled += 1

    await session.commit()
    logger.info('category seed/backfill: %s', result.summary())
    return result


async def _create_skeleton(session: AsyncSession) -> None:
    rental = Category(title='Аренда', fulfillment=FulfillmentEnum.RENTAL, sort=0)
    auto = Category(title='Автовыдача', fulfillment=FulfillmentEnum.AUTODELIVERY, sort=1)
    other = Category(title='Прочее', fulfillment=FulfillmentEnum.OTHER, sort=2)
    session.add_all([rental, auto, other])
    await session.flush()
    session.add_all([
        Category(title='Steam', parent_id=rental.id, provider=ProviderEnum.STEAM, sort=0),
        Category(title='X', parent_id=rental.id, provider=ProviderEnum.X, sort=1),
    ])
    await session.flush()
