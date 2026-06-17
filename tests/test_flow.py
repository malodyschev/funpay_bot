from datetime import datetime, timedelta

import pytest_asyncio

from app.crypto import encrypt
from app.database import async_engine, async_session
from app.rental.admin_bot.notifier import AdminNotifier
from app.rental.common.enums import (
    AccountStatusEnum,
    AccountTypeEnum,
    ExtensionReasonEnum,
    RentalStatusEnum,
)
from app.rental.funpay.events import NewMessageEvent, NewOrderEvent
from app.rental.funpay.fake import FakeFunPayConnector
from app.rental.models import Base
from app.rental.models.account import Account
from app.rental.models.lot import Lot
from app.rental.repositories.account import AccountRepository
from app.rental.repositories.extension import ExtensionRepository
from app.rental.repositories.rental import RentalRepository
from app.rental.services.admin import AdminService
from app.rental.services.expire_rental import ExpireRentalService
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.guard_code import GuardCodeService
from app.rental.services.info import InfoService
from app.rental.services.new_order import NewOrderService
from app.rental.services.refund import RefundService
from app.rental.steam.fake import FakeSteamModule
from app.runtime import RentalDeps, runtime


class RecordingNotifier(AdminNotifier):
    def __init__(self):
        self.messages: list[str] = []
        self.refund_requests: list[tuple[str, str]] = []

    async def notify(self, text: str) -> None:
        self.messages.append(text)

    async def request_refund(self, order_id: str, reason: str) -> None:
        self.refund_requests.append((order_id, reason))


@pytest_asyncio.fixture
async def session():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as s:
        yield s


def make_deps():
    return RentalDeps(
        funpay=FakeFunPayConnector(),
        steam=FakeSteamModule(),
        notifier=RecordingNotifier(),
    )


async def seed_lot(session, *, duration_minutes=60) -> Lot:
    lot = Lot(
        title='Аренда Dota 2 на 1 час',
        game='Dota 2',
        duration_minutes=duration_minutes,
        delivery_template='Логин: {login}\nПароль: {password}\nСрок: {minutes} мин. !code для кода',
        active=True,
    )
    session.add(lot)
    await session.commit()
    return lot


async def seed_account(session, lot_id, *, type_=AccountTypeEnum.ONLINE) -> Account:
    account = Account(
        lot_id=lot_id,
        login='steam_login',
        password_enc=encrypt('old_password'),
        steam_id='76561190000000000',
        shared_secret_enc=encrypt('shared'),
        identity_secret_enc=encrypt('identity'),
        device_id='android:test',
        status=AccountStatusEnum.FREE,
        type=type_,
    )
    session.add(account)
    await session.commit()
    return account


def order_event(order_id='ORDER-1', chat_id=555, amount=1):
    return NewOrderEvent(
        order_id=order_id,
        lot_title='Аренда Dota 2 на 1 час',
        buyer_id=42,
        buyer_username='buyer',
        chat_id=chat_id,
        amount=amount,
    )


async def test_w1_new_order_delivers_and_reserves(session):
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id)
    deps = make_deps()

    await NewOrderService(session, deps).handle(order_event())

    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert rental is not None
    assert rental.status == RentalStatusEnum.ACTIVE
    reserved = await AccountRepository(session).get(account.id)
    assert reserved.status == AccountStatusEnum.RENTED
    assert len(deps.funpay.sent) == 1
    chat_id, text = deps.funpay.sent[0]
    assert chat_id == 555
    assert 'steam_login' in text and 'old_password' in text


async def test_w1_quantity_multiplies_duration(session):
    lot = await seed_lot(session, duration_minutes=60)
    await seed_account(session, lot.id)
    deps = make_deps()

    await NewOrderService(session, deps).handle(order_event(amount=2))

    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert rental is not None
    # 2 шт. × 60 мин = 120 мин аренды
    assert rental.expires_at - rental.started_at == timedelta(minutes=120)


def test_clean_lot_title_strips_amount_suffix():
    from app.rental.funpay.listener import _clean_lot_title

    assert _clean_lot_title('Аренда Dota 2 на 1 час, 2 шт.') == 'Аренда Dota 2 на 1 час'
    assert _clean_lot_title('Аренда Dota 2 на 1 час, 1 000 pcs.') == 'Аренда Dota 2 на 1 час'
    assert _clean_lot_title('Аренда Dota 2 на 1 час') == 'Аренда Dota 2 на 1 час'


async def test_w1_idempotent_on_duplicate_order(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()

    await NewOrderService(session, deps).handle(order_event())
    await NewOrderService(session, deps).handle(order_event())  # дубль

    rentals = await RentalRepository(session).get_active()
    assert len(rentals) == 1
    assert len(deps.funpay.sent) == 1


async def test_w1_no_free_account_requests_refund(session):
    await seed_lot(session)  # лот есть, аккаунтов нет
    deps = make_deps()

    await NewOrderService(session, deps).handle(order_event())

    assert deps.notifier.refund_requests == [('ORDER-1', 'no free account')]
    assert len(deps.funpay.sent) == 1  # извинение покупателю


async def test_w2_guard_code(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await GuardCodeService(session, deps).handle(
        NewMessageEvent(chat_id=555, message_id=1, author_id=42, text='!code'),
    )

    assert 'ABCDE' in deps.funpay.sent[-1][1]


async def test_w4_extend_on_review(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())
    rental_before = await RentalRepository(session).get_by_order_id('ORDER-1')
    old_expires = rental_before.expires_at

    await ExtendRentalService(session, deps).extend_by_order(
        'ORDER-1', 60, ExtensionReasonEnum.REVIEW,
    )

    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert rental.expires_at == old_expires + timedelta(minutes=60)
    assert rental.extended_minutes == 60
    extensions = await ExtensionRepository(session).get_all(rental_id=rental.id)
    assert len(extensions) == 1


async def test_w3_expire_deauthorizes_and_frees(session):
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id)
    deps = make_deps()

    deauthorized: list[str] = []

    async def _record_deauthorize(credentials):
        deauthorized.append(credentials.login)
        return 1

    deps.steam.deauthorize = _record_deauthorize

    await NewOrderService(session, deps).handle(order_event())
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    old_password_enc = (await AccountRepository(session).get(account.id)).password_enc

    await ExpireRentalService(session, deps).handle(rental.id)

    freed = await AccountRepository(session).get(account.id)
    assert freed.status == AccountStatusEnum.FREE
    assert freed.password_enc == old_password_enc  # пароль НЕ меняется
    assert deauthorized == [account.login]  # сессии деавторизованы
    expired = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert expired.status == RentalStatusEnum.EXPIRED


async def test_w3_deauthorize_failure_sets_error_and_alerts(session, monkeypatch):
    from app.rental.services import expire_rental

    monkeypatch.setattr(expire_rental.settings, 'deauthorize_retries', 1)
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id)
    deps = make_deps()

    async def _fail_deauthorize(credentials):
        raise RuntimeError('steam недоступен')

    deps.steam.deauthorize = _fail_deauthorize

    await NewOrderService(session, deps).handle(order_event())
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')

    await ExpireRentalService(session, deps).handle(rental.id)

    errored = await AccountRepository(session).get(account.id)
    assert errored.status == AccountStatusEnum.ERROR
    rental_after = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert rental_after.status == RentalStatusEnum.ERROR
    assert len(deps.notifier.messages) == 1  # админу ушёл алерт


async def test_w3_offline_account_not_rotated(session):
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id, type_=AccountTypeEnum.OFFLINE)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    old_password_enc = (await AccountRepository(session).get(account.id)).password_enc

    await ExpireRentalService(session, deps).handle(rental.id)

    freed = await AccountRepository(session).get(account.id)
    assert freed.status == AccountStatusEnum.FREE
    assert freed.password_enc == old_password_enc  # пароль НЕ менялся


async def test_w5_refund_releases_account(session):
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await RefundService(session, deps).execute('ORDER-1')

    assert deps.funpay.refunded == ['ORDER-1']
    freed = await AccountRepository(session).get(account.id)
    assert freed.status == AccountStatusEnum.FREE
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    assert rental.status == RentalStatusEnum.REFUNDED


async def test_extend_command_gives_link(session):
    ext = Lot(
        title='Продление Dota +1 час',
        duration_minutes=60,
        delivery_template='-',
        active=True,
        is_extension=True,
        funpay_lot_id=4242,
    )
    session.add(ext)
    await session.commit()
    deps = make_deps()

    await InfoService(session, deps).extend_info(555)
    text = deps.funpay.sent[-1][1]
    assert 'offer?id=4242' in text and '+60' in text


async def test_refund_command_asks_admin(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await InfoService(session, deps).request_refund(555)

    # админу ушёл запрос с order_id, покупателю — подтверждение
    assert deps.notifier.refund_requests[-1][0] == 'ORDER-1'
    assert 'возврат' in deps.funpay.sent[-1][1].lower()


async def test_refund_command_without_rental(session):
    deps = make_deps()
    await InfoService(session, deps).request_refund(555)
    assert deps.notifier.refund_requests == []  # нет аренды → админа не дёргаем


async def test_refund_decline_notifies_buyer(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await RefundService(session, deps).decline('ORDER-1')
    assert 'отклонил' in deps.funpay.sent[-1][1].lower()


async def test_toggle_lot_extension(session):
    lot = await seed_lot(session)
    svc = AdminService(session, make_deps())
    assert lot.is_extension is False

    assert await svc.toggle_lot_extension(lot.id) is True
    refreshed = await svc.get_lot(lot.id)
    assert refreshed.is_extension is True

    assert await svc.toggle_lot_extension(lot.id) is False
    refreshed = await svc.get_lot(lot.id)
    assert refreshed.is_extension is False


async def test_w6_info_commands(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await InfoService(session, deps).time_left(555)
    assert 'осталось' in deps.funpay.sent[-1][1]
    await InfoService(session, deps).stock(555)
    # лот определён по активной аренде → ответ про этот лот + подсказка !free-all
    assert '!free-all' in deps.funpay.sent[-1][1]
    await InfoService(session, deps).faq(555)
    assert 'Команды' in deps.funpay.sent[-1][1]


async def test_free_before_purchase_uses_viewed_lot(session):
    """!free до покупки: лот берём из «Покупатель смотрит» (funpay_lot_id)."""
    lot = await seed_lot(session)
    lot.funpay_lot_id = 999
    await session.commit()
    await seed_account(session, lot.id)
    deps = make_deps()
    deps.funpay.viewed_lot_id = 999  # покупатель смотрит этот оффер

    await InfoService(session, deps).stock(777)  # активной аренды нет
    text = deps.funpay.sent[-1][1]
    assert lot.title in text and 'свободно' in text


async def test_free_all_lists_every_lot(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()

    await InfoService(session, deps).stock_all(123)
    text = deps.funpay.sent[-1][1]
    assert lot.title in text and 'шт.' in text


async def _make_active_rental(session, deps):
    """Создать активную аренду через боевой W1 и вернуть (account, rental)."""
    lot = await seed_lot(session)
    account = await seed_account(session, lot.id)
    await NewOrderService(session, deps).handle(order_event())
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    return account, rental


async def test_admin_dashboard_and_stock(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    await seed_account(session, lot.id)
    svc = AdminService(session, make_deps())

    dash = await svc.dashboard()
    assert dash.status_counts.get(AccountStatusEnum.FREE) == 2
    assert dash.active_rentals == 0

    stock = await svc.lots_with_stock()
    assert len(stock) == 1
    assert stock[0].free == 2 and stock[0].total == 2


async def test_admin_kick_deauthorizes_and_frees(session):
    deps = make_deps()
    kicked: list[str] = []

    async def _record(credentials):
        kicked.append(credentials.login)
        return 1

    deps.steam.deauthorize = _record
    account, rental = await _make_active_rental(session, deps)

    result = await AdminService(session, deps).kick(account.id)

    assert 'досрочно' in result.lower()
    assert kicked == [account.login]
    freed = await AccountRepository(session).get(account.id)
    assert freed.status == AccountStatusEnum.FREE
    expired = await RentalRepository(session).get(rental.id)
    assert expired.status == RentalStatusEnum.EXPIRED


async def test_admin_free_without_deauth(session):
    deps = make_deps()
    called: list[str] = []
    deps.steam.deauthorize = lambda creds: called.append(creds.login)  # noqa: ARG005
    account, rental = await _make_active_rental(session, deps)

    await AdminService(session, deps).free_without_deauth(account.id)

    assert called == []  # деавторизация НЕ вызывалась
    freed = await AccountRepository(session).get(account.id)
    assert freed.status == AccountStatusEnum.FREE
    expired = await RentalRepository(session).get(rental.id)
    assert expired.status == RentalStatusEnum.EXPIRED


async def test_admin_set_status_offline_ends_rental(session):
    deps = make_deps()
    account, rental = await _make_active_rental(session, deps)

    await AdminService(session, deps).set_status(account.id, AccountStatusEnum.OFFLINE)

    updated = await AccountRepository(session).get(account.id)
    assert updated.status == AccountStatusEnum.OFFLINE
    expired = await RentalRepository(session).get(rental.id)
    assert expired.status == RentalStatusEnum.EXPIRED


async def test_admin_extend_and_notes_and_reveal(session):
    deps = make_deps()
    account, rental = await _make_active_rental(session, deps)
    svc = AdminService(session, deps)

    old_expires = (await RentalRepository(session).get(rental.id)).expires_at
    await svc.extend(account.id, 30)
    assert (await RentalRepository(session).get(rental.id)).expires_at > old_expires

    await svc.set_notes(account.id, 'тестовая заметка')
    assert (await AccountRepository(session).get(account.id)).notes == 'тестовая заметка'

    creds = await svc.reveal_credentials(account.id)
    assert creds.login == account.login
    assert creds.password == 'old_password'  # из seed_account
    assert creds.code == 'ABCDE'  # FakeSteamModule


async def test_extension_lot_extends_active_rental(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())
    rental = await RentalRepository(session).get_by_order_id('ORDER-1')
    old_expires = rental.expires_at

    ext_lot = Lot(
        title='Продление +30',
        duration_minutes=30,
        delivery_template='-',
        active=True,
        is_extension=True,
    )
    session.add(ext_lot)
    await session.commit()

    ext_event = NewOrderEvent(
        order_id='ORDER-EXT',
        lot_title='Продление +30',
        buyer_id=42,
        buyer_username='buyer',
        chat_id=555,
    )
    await NewOrderService(session, deps).handle(ext_event)

    updated = await RentalRepository(session).get(rental.id)
    assert updated.expires_at == old_expires + timedelta(minutes=30)
    assert updated.extended_minutes == 30

    # тот же заказ-продление повторно → без двойного продления (идемпотентность)
    await NewOrderService(session, deps).handle(ext_event)
    again = await RentalRepository(session).get(rental.id)
    assert again.expires_at == old_expires + timedelta(minutes=30)


async def test_extension_without_active_rental_alerts(session):
    await seed_lot(session)
    deps = make_deps()
    ext_lot = Lot(
        title='Продление +30',
        duration_minutes=30,
        delivery_template='-',
        active=True,
        is_extension=True,
    )
    session.add(ext_lot)
    await session.commit()

    await NewOrderService(session, deps).handle(NewOrderEvent(
        order_id='ORDER-EXT',
        lot_title='Продление +30',
        buyer_id=999,
        buyer_username='nobody',
        chat_id=777,
    ))

    assert len(deps.notifier.messages) == 1  # алерт «продление без аренды»
    assert any('нет активной аренды' in t for _, t in deps.funpay.sent)


async def test_sync_lots_creates_draft_and_updates(session):
    from types import SimpleNamespace as N

    from app.rental.funpay.lot_sync import sync_lots
    from app.rental.repositories.lot import LotRepository

    fp_lot = N(id=12345, active=True, description='Аренда CS2', price=100.0, subcategory=N(id=999))
    account = N(
        id=1,
        get_user=lambda uid: N(get_lots=lambda: [fp_lot]),
        get_my_subcategory_lots=lambda sid: [fp_lot],
    )

    result = await sync_lots(session, account)
    assert (result.created, result.updated) == (1, 0)
    lot = await LotRepository(session).get_or_none(funpay_lot_id=12345)
    assert lot.title == 'Аренда CS2'
    assert lot.active is False  # черновик, пока не настроен
    assert lot.duration_minutes == 0
    assert lot.funpay_node_id == 999

    # повторная синхронизация → апдейт, не дубль, активацию не навязывает
    fp_lot.price = 150.0
    result2 = await sync_lots(session, account)
    assert (result2.created, result2.updated) == (0, 1)
    refreshed = await LotRepository(session).get_or_none(funpay_lot_id=12345)
    assert refreshed.price == 150.0
    assert refreshed.active is False


async def test_lot_auto_hide_on_sale_and_show_on_return(session):
    lot = Lot(
        title='CS2 аренда',
        game='CS2',
        duration_minutes=60,
        delivery_template='Логин: {login} Пароль: {password}',
        active=True,
        funpay_lot_id=555,
    )
    session.add(lot)
    await session.commit()
    await seed_account(session, lot.id)
    deps = make_deps()

    order = NewOrderEvent(
        order_id='O1', lot_title='CS2 аренда', buyer_id=7, buyer_username='b', chat_id=70,
    )
    await NewOrderService(session, deps).handle(order)
    assert deps.funpay.lot_active[-1] == (555, False)  # распродан → скрыт

    rental = await RentalRepository(session).get_by_order_id('O1')
    await ExpireRentalService(session, deps).handle(rental.id)
    assert deps.funpay.lot_active[-1] == (555, True)  # вернулся → показан


def _free_account(lot_id, login, steam_id):
    return Account(
        lot_id=lot_id, login=login, password_enc=encrypt('p'), steam_id=steam_id,
        shared_secret_enc=encrypt('s'), identity_secret_enc=encrypt('i'),
        status=AccountStatusEnum.FREE, type=AccountTypeEnum.ONLINE,
    )


async def test_two_lots_same_title_rent_independently(session):
    deps = make_deps()
    lot_a = Lot(title='CS2', duration_minutes=60, delivery_template='{login}/{password}',
                active=True, funpay_lot_id=11)
    lot_b = Lot(title='CS2', duration_minutes=60, delivery_template='{login}/{password}',
                active=True, funpay_lot_id=22)
    session.add_all([lot_a, lot_b])
    await session.commit()
    session.add_all([_free_account(lot_a.id, 'l1', 's1'), _free_account(lot_b.id, 'l2', 's2')])
    await session.commit()

    await NewOrderService(session, deps).handle(
        NewOrderEvent(order_id='O1', lot_title='CS2', buyer_id=1, buyer_username='b1', chat_id=1))
    await NewOrderService(session, deps).handle(
        NewOrderEvent(order_id='O2', lot_title='CS2', buyer_id=2, buyer_username='b2', chat_id=2))

    rentals = await RentalRepository(session).get_active()
    assert len(rentals) == 2  # две аренды на два разных аккаунта/лота
    assert {r.lot_id for r in rentals} == {lot_a.id, lot_b.id}
    assert (11, False) in deps.funpay.lot_active
    assert (22, False) in deps.funpay.lot_active


async def test_sync_creates_separate_lots_for_same_title(session):
    from types import SimpleNamespace as N

    from app.rental.funpay.lot_sync import sync_lots
    from app.rental.repositories.lot import LotRepository

    fp1 = N(id=11, active=True, description='CS2', price=10.0, subcategory=N(id=1))
    fp2 = N(id=22, active=True, description='CS2', price=10.0, subcategory=N(id=1))
    account = N(
        id=1,
        get_user=lambda uid: N(get_lots=lambda: [fp1, fp2]),
        get_my_subcategory_lots=lambda sid: [fp1, fp2],
    )

    result = await sync_lots(session, account)
    assert (result.created, result.updated) == (2, 0)
    lots = await LotRepository(session).get_all(title='CS2')
    assert len(lots) == 2
    assert {lot.funpay_lot_id for lot in lots} == {11, 22}
