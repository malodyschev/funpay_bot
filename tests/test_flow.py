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
        delivery_template='Логин: {login}\nПароль: {password}\nСрок: {minutes} мин. !код для кода',
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


def order_event(order_id='ORDER-1', chat_id=555):
    return NewOrderEvent(
        order_id=order_id,
        lot_title='Аренда Dota 2 на 1 час',
        buyer_id=42,
        buyer_username='buyer',
        chat_id=chat_id,
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
        NewMessageEvent(chat_id=555, message_id=1, author_id=42, text='!код'),
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


async def test_w6_info_commands(session):
    lot = await seed_lot(session)
    await seed_account(session, lot.id)
    deps = make_deps()
    await NewOrderService(session, deps).handle(order_event())

    await InfoService(session, deps).time_left(555)
    assert 'осталось' in deps.funpay.sent[-1][1]
    await InfoService(session, deps).stock(555)
    assert 'Свободных' in deps.funpay.sent[-1][1]
    await InfoService(session, deps).faq(555)
    assert 'Команды' in deps.funpay.sent[-1][1]


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
