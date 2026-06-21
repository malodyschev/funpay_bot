import pytest_asyncio

from app.database import async_engine, async_session
from app.rental.common.enums import FulfillmentEnum, ProviderEnum
from app.rental.models import Base, Category
from app.rental.providers.registry import get_provider
from app.rental.providers.steam import SteamProvider
from app.rental.providers.x import XProvider
from app.rental.repositories.category import CategoryRepository


@pytest_asyncio.fixture
async def session():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as s:
        yield s


async def _seed_tree(session) -> dict[str, int]:
    """Аренда → {Steam → Dota2, X}; провайдер/тип наследуются вниз."""
    rental = Category(title='Аренда', fulfillment=FulfillmentEnum.RENTAL)
    session.add(rental)
    await session.flush()
    steam = Category(title='Steam', parent_id=rental.id, provider=ProviderEnum.STEAM)
    x = Category(title='X', parent_id=rental.id, provider=ProviderEnum.X)
    session.add_all([steam, x])
    await session.flush()
    dota = Category(title='Dota2', parent_id=steam.id)  # provider наследует от Steam
    session.add(dota)
    await session.flush()
    await session.commit()
    return {'rental': rental.id, 'steam': steam.id, 'x': x.id, 'dota': dota.id}


async def test_resolve_inherits_from_ancestors(session):
    ids = await _seed_tree(session)
    repo = CategoryRepository(session)

    assert await repo.resolve(ids['dota']) == (FulfillmentEnum.RENTAL, ProviderEnum.STEAM)
    assert await repo.resolve(ids['x']) == (FulfillmentEnum.RENTAL, ProviderEnum.X)
    assert await repo.resolve(ids['rental']) == (FulfillmentEnum.RENTAL, None)
    # лот без категории (legacy) — ничего не наследует
    assert await repo.resolve(None) == (None, None)


async def test_get_children_navigation(session):
    ids = await _seed_tree(session)
    repo = CategoryRepository(session)

    roots = await repo.get_children(None)
    assert [c.title for c in roots] == ['Аренда']
    steam_children = await repo.get_children(ids['steam'])
    assert [c.title for c in steam_children] == ['Dota2']


def test_registry_maps_provider():
    # None (legacy-лот) → Steam ради обратной совместимости.
    assert isinstance(get_provider(None, deps=None), SteamProvider)
    assert isinstance(get_provider(ProviderEnum.STEAM, deps=None), SteamProvider)
    assert isinstance(get_provider(ProviderEnum.X, deps=None), XProvider)
