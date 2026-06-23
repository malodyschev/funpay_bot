import pytest
import pytest_asyncio
import sqlalchemy as sa

from app.database import async_engine, async_session
from app.rental.common.enums import FulfillmentEnum, ProviderEnum
from app.rental.models import Base, Category
from app.rental.models.lot import Lot
from app.rental.providers.registry import get_provider
from app.rental.providers.steam import SteamProvider
from app.rental.repositories.category import CategoryRepository
from app.rental.services.admin import AdminService
from app.rental.services.category_setup import seed_and_backfill
from app.runtime import RentalDeps


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
    x = Category(title='X', parent_id=rental.id, provider=ProviderEnum.CHAT)
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
    assert await repo.resolve(ids['x']) == (FulfillmentEnum.RENTAL, ProviderEnum.CHAT)
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
    # Chat не ходит через провайдер — get_provider для CHAT бьёт явной ошибкой.
    with pytest.raises(ValueError, match='ChatRentalService'):
        get_provider(ProviderEnum.CHAT, deps=None)


async def test_seed_and_backfill_assigns_legacy_lots(session):
    """Старые лоты без категории развешиваются: Dota→Steam/<игра>, автовыдача→Автовыдача."""
    session.add_all([
        Lot(title='Dota A', game='Dota 2', duration_minutes=60, delivery_template='t'),
        Lot(title='Dota B', game='Dota 2', duration_minutes=120, delivery_template='t'),
        Lot(title='Key', duration_minutes=0, delivery_template='t', is_autodelivery=True),
    ])
    await session.commit()

    result = await seed_and_backfill(session)
    assert result.skeleton_created
    assert result.games_created == 1  # одна подкатегория «Dota 2»

    lots = list(await session.scalars(sa.select(Lot)))
    assert all(lot.category_id is not None for lot in lots)

    repo = CategoryRepository(session)
    dota = next(lot for lot in lots if lot.title == 'Dota A')
    fulfillment, provider = await repo.resolve(dota.category_id)
    assert (fulfillment, provider) == (FulfillmentEnum.RENTAL, ProviderEnum.STEAM)

    # повторный прогон ничего не трогает (идемпотентность)
    again = await seed_and_backfill(session)
    assert again.lots_backfilled == 0


async def test_uncategorized_bucket_and_set_category(session):
    """Синканный лот без категории виден в «неразобранных» и назначается в дерево."""
    await seed_and_backfill(session)  # скелет дерева
    svc = AdminService(session, RentalDeps(funpay=None, steam=None, notifier=None))

    lot = Lot(title='Synced draft', duration_minutes=0, delivery_template='t', active=False)
    session.add(lot)
    await session.commit()

    assert any(ls.lot.id == lot.id for ls in await svc.uncategorized_lots())

    paths = await svc.category_paths()
    steam = next(c for c, _ in paths if c.provider == ProviderEnum.STEAM)
    assert await svc.set_lot_category(lot.id, steam.id)

    assert all(ls.lot.id != lot.id for ls in await svc.uncategorized_lots())
    assert (await svc.get_lot(lot.id)).category_id == steam.id
