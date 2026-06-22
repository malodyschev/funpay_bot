import base64
from datetime import datetime, timedelta

import pytest_asyncio

import app.rental.chat.totp as totp_mod
from app.crypto import encrypt
from app.database import async_engine, async_session
from app.rental.chat.totp import totp_now
from app.rental.common.enums import ChatRentalStatusEnum, FulfillmentEnum, ProviderEnum
from app.rental.funpay.fake import FakeFunPayConnector
from app.rental.models import Base, Category
from app.rental.models.chat_account import ChatAccount
from app.rental.models.chat_rental import ChatRental
from app.rental.models.lot import Lot
from app.rental.repositories.chat_rental import ChatRentalRepository
from app.rental.services.chat_rental import ChatRentalService
from app.runtime import RentalDeps


_RFC_SECRET = base64.b32encode(b'12345678901234567890').decode()


def _deps() -> RentalDeps:
    return RentalDeps(funpay=FakeFunPayConnector(), steam=None, notifier=None)


@pytest_asyncio.fixture
async def session():
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session() as s:
        yield s


async def _category(session) -> int:
    cat = Category(title='ChatGPT', provider=ProviderEnum.CHAT, fulfillment=FulfillmentEnum.RENTAL)
    session.add(cat)
    await session.commit()
    return cat.id


async def _lot(session, category_id, *, minutes=60) -> Lot:
    lot = Lot(title='X', category_id=category_id, duration_minutes=minutes, delivery_template='t')
    session.add(lot)
    await session.commit()
    return lot


async def _account(session, category_id, *, slots, login='u', secret=_RFC_SECRET) -> ChatAccount:
    acc = ChatAccount(
        category_id=category_id,
        login=login,
        password_enc=encrypt('pwd'),
        totp_secret_enc=encrypt(secret) if secret else None,
        slots=slots,
    )
    session.add(acc)
    await session.commit()
    return acc


async def _rental(session, account_id, lot_id, *, chat_id, order_id, expires_at) -> None:
    session.add(ChatRental(
        chat_account_id=account_id,
        lot_id=lot_id,
        buyer_id=chat_id,
        chat_id=chat_id,
        funpay_order_id=order_id,
        expires_at=expires_at,
        status=ChatRentalStatusEnum.ACTIVE,
    ))
    await session.commit()


# ---------- TOTP ----------

def test_totp_rfc6238_vector(monkeypatch):
    monkeypatch.setattr(totp_mod.time, 'time', lambda: 59)
    assert totp_now(_RFC_SECRET) == '287082'


# ---------- балансировка ----------

async def test_place_picks_least_loaded(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc_a = await _account(session, cat, slots=5, login='a')
    acc_b = await _account(session, cat, slots=5, login='b')
    future = datetime.now() + timedelta(hours=1)
    await _rental(session, acc_a.id, lot.id, chat_id=1, order_id='o1', expires_at=future)
    await _rental(session, acc_a.id, lot.id, chat_id=2, order_id='o2', expires_at=future)

    result = await ChatRentalService(session, _deps()).place(
        lot, buyer_id=9, buyer_username='b', chat_id=9, order_id='new',
    )
    assert result.reason == 'ok'
    assert result.account.id == acc_b.id  # B менее загружен


async def test_place_no_capacity(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=1)
    await _rental(
        session, acc.id, lot.id, chat_id=1, order_id='o1',
        expires_at=datetime.now() + timedelta(hours=1),
    )
    result = await ChatRentalService(session, _deps()).place(
        lot, buyer_id=9, buyer_username='b', chat_id=9, order_id='new',
    )
    assert result.reason == 'no_capacity'
    assert result.account is None


async def test_place_idempotent(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    await _account(session, cat, slots=5)
    svc = ChatRentalService(session, _deps())
    first = await svc.place(lot, buyer_id=9, buyer_username='b', chat_id=9, order_id='dup')
    second = await svc.place(lot, buyer_id=9, buyer_username='b', chat_id=9, order_id='dup')
    assert first.reason == 'ok'
    assert second.reason == 'duplicate'
    assert await ChatRentalRepository(session).count_active_by_account(first.account.id) == 1


# ---------- код ----------

async def test_code_for_chat(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    await _account(session, cat, slots=5)
    svc = ChatRentalService(session, _deps())
    await svc.place(lot, buyer_id=7, buyer_username='b', chat_id=7, order_id='o')

    ok = await svc.code_for_chat(7)
    assert ok.reason == 'ok'
    assert ok.code is not None and len(ok.code) == 6

    none = await svc.code_for_chat(999)
    assert none.reason == 'none'


async def test_first_code_sets_anchor_without_clock_reset(session):
    """Первый !chat-code фиксирует code_requested_at, но срок НЕ двигает (идёт с оплаты)."""
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=5)
    started = datetime.now() - timedelta(minutes=10)
    orig_expires = started + timedelta(minutes=60)
    session.add(ChatRental(
        chat_account_id=acc.id, lot_id=lot.id, buyer_id=5, chat_id=5,
        funpay_order_id='o', started_at=started, expires_at=orig_expires,
        status=ChatRentalStatusEnum.ACTIVE,
    ))
    await session.commit()
    svc = ChatRentalService(session, _deps())
    repo = ChatRentalRepository(session)

    first = await svc.code_for_chat(5)
    assert first.reason == 'ok'
    rental = await repo.get_by_order_id('o')
    assert rental.code_requested_at is not None
    assert rental.expires_at == orig_expires  # срок с оплаты — не пересчитан
    anchor = rental.code_requested_at

    second = await svc.code_for_chat(5)
    assert second.reason == 'ok'
    assert (await repo.get_by_order_id('o')).code_requested_at == anchor


async def test_extend_for_review_adds_day(session):
    """Отзыв продлевает активную Chat-аренду на +1 день + шлёт сообщение."""
    from app.rental.services.chat_rental import CHAT_REVIEW_BONUS_MINUTES

    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=5)
    expires = datetime.now() + timedelta(hours=1)
    await _rental(session, acc.id, lot.id, chat_id=7, order_id='o', expires_at=expires)

    deps = _deps()
    extended = await ChatRentalService(session, deps).extend_for_review(7)
    assert extended is True
    rental = await ChatRentalRepository(session).get_by_order_id('o')
    assert rental.expires_at >= expires + timedelta(minutes=CHAT_REVIEW_BONUS_MINUTES - 1)
    assert deps.funpay.sent  # пришло благодарственное сообщение

    assert await ChatRentalService(session, deps).extend_for_review(999) is False


async def test_code_for_chat_expired(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=5)
    await _rental(
        session, acc.id, lot.id, chat_id=5, order_id='o',
        expires_at=datetime.now() - timedelta(minutes=1),  # уже истекла
    )
    result = await ChatRentalService(session, _deps()).code_for_chat(5)
    assert result.reason == 'expired'
    assert result.code is None


async def test_code_for_chat_multiple_rentals_no_crash(session):
    """Несколько аренд на один чат → code_for_chat не падает (MultipleResultsFound)."""
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=5)
    past = datetime.now() - timedelta(minutes=1)
    await _rental(session, acc.id, lot.id, chat_id=5, order_id='o1', expires_at=past)
    await _rental(session, acc.id, lot.id, chat_id=5, order_id='o2', expires_at=past)

    result = await ChatRentalService(session, _deps()).code_for_chat(5)
    assert result.reason == 'expired'


async def test_warn_due_warns_once(session):
    """Предупреждение об окончании шлётся раз (warned=True), повторно — нет."""
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=5)
    soon = datetime.now() + timedelta(minutes=30)  # внутри окна 60 мин
    await _rental(session, acc.id, lot.id, chat_id=8, order_id='o', expires_at=soon)

    deps = _deps()
    svc = ChatRentalService(session, deps)
    assert await svc.warn_due() == 1
    assert deps.funpay.sent
    assert await svc.warn_due() == 0  # уже предупредили


# ---------- истечение освобождает слот ----------

async def test_expire_due_frees_slot(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=1)
    await _rental(
        session, acc.id, lot.id, chat_id=5, order_id='o',
        expires_at=datetime.now() - timedelta(minutes=1),
    )
    deps = _deps()
    svc = ChatRentalService(session, deps)

    alerts = await svc.expire_due()
    assert len(alerts) == 1
    assert await ChatRentalRepository(session).count_active_by_account(acc.id) == 0
    # покупателю ушло сообщение об окончании
    assert any('закончилась' in t for _c, t in deps.funpay.sent)

    # слот освободился — новый заказ проходит
    result = await svc.place(lot, buyer_id=9, buyer_username='b', chat_id=9, order_id='new')
    assert result.reason == 'ok'


# ---------- замена аккаунта ----------

async def test_replace_account_moves_rentals_and_notifies(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    old = await _account(session, cat, slots=2, login='old')
    new = await _account(session, cat, slots=5, login='new')
    future = datetime.now() + timedelta(hours=1)
    await _rental(session, old.id, lot.id, chat_id=11, order_id='o1', expires_at=future)
    await _rental(session, old.id, lot.id, chat_id=22, order_id='o2', expires_at=future)

    deps = _deps()
    result = await ChatRentalService(session, deps).replace_account(old.id, new.id)
    assert result.ok
    assert result.moved == 2

    repo = ChatRentalRepository(session)
    assert await repo.count_active_by_account(old.id) == 0
    assert await repo.count_active_by_account(new.id) == 2
    # каждому арендатору ушло сообщение с новым логином
    assert len(deps.funpay.sent) == 2
    assert all('new' in text for _chat, text in deps.funpay.sent)


async def test_new_order_x_delivers_creds(session):
    """W1 для X: заказ → least-loaded аккаунт → выдача login+password + аренда в БД."""
    from app.rental.funpay.events import NewOrderEvent
    from app.rental.repositories.chat_rental import ChatRentalRepository
    from app.rental.services.new_order import NewOrderService

    cat = await _category(session)
    lot = Lot(
        title='ChatGPT 1ч',
        category_id=cat,
        duration_minutes=60,
        delivery_template='Почта: {login}\nПароль: {password}',
        active=True,
    )
    session.add(lot)
    await session.commit()
    await _account(session, cat, slots=5, login='shared@x')

    deps = _deps()
    event = NewOrderEvent(
        order_id='X1', lot_title='ChatGPT 1ч', buyer_id=10,
        buyer_username='buyer', chat_id=10, amount=1,
    )
    await NewOrderService(session, deps).handle(event)

    assert any('shared@x' in text for _chat, text in deps.funpay.sent)
    assert any('!chat-code' in text for _chat, text in deps.funpay.sent)
    assert await ChatRentalRepository(session).get_by_order_id('X1') is not None


async def test_replace_account_not_enough_slots(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    old = await _account(session, cat, slots=2, login='old')
    new = await _account(session, cat, slots=1, login='new')
    future = datetime.now() + timedelta(hours=1)
    await _rental(session, old.id, lot.id, chat_id=11, order_id='o1', expires_at=future)
    await _rental(session, old.id, lot.id, chat_id=22, order_id='o2', expires_at=future)

    result = await ChatRentalService(session, _deps()).replace_account(old.id, new.id)
    assert not result.ok
    assert result.reason == 'not_enough_slots'


# ---------- команды покупателя + видимость пула + возврат ----------

async def test_buyer_commands_chat(session):
    cat = await _category(session)
    lot = await _lot(session, cat)
    await _account(session, cat, slots=5, login='shared@chat')
    deps = _deps()
    svc = ChatRentalService(session, deps)
    await svc.place(lot, buyer_id=7, buyer_username='b', chat_id=7, order_id='o')

    assert await svc.send_time_left(7) is True
    assert await svc.send_credentials(7) is True
    assert any('shared@chat' in t for _c, t in deps.funpay.sent)
    assert await svc.send_time_left(999) is False


async def test_sync_pool_visibility_hides_when_full(session):
    cat = await _category(session)
    lot = Lot(
        title='L', category_id=cat, duration_minutes=60,
        delivery_template='t', active=True, funpay_lot_id=555,
    )
    session.add(lot)
    await session.commit()
    acc = await _account(session, cat, slots=1)
    deps = _deps()
    svc = ChatRentalService(session, deps)

    await svc.sync_pool_visibility(cat)
    assert deps.funpay.lot_active[-1] == (555, True)  # есть место → виден

    await _rental(
        session, acc.id, lot.id, chat_id=1, order_id='o',
        expires_at=datetime.now() + timedelta(hours=1),
    )
    await svc.sync_pool_visibility(cat)
    assert deps.funpay.lot_active[-1] == (555, False)  # пул заполнен → скрыт


async def test_refund_closes_chat_rental_frees_slot(session):
    from app.rental.services.refund import RefundService

    cat = await _category(session)
    lot = await _lot(session, cat)
    acc = await _account(session, cat, slots=1)
    deps = _deps()
    res = await ChatRentalService(session, deps).place(
        lot, buyer_id=7, buyer_username='b', chat_id=7, order_id='ORD',
    )
    assert res.reason == 'ok'
    assert await ChatRentalRepository(session).count_active_by_account(acc.id) == 1

    await RefundService(session, deps).execute('ORD')
    assert 'ORD' in deps.funpay.refunded
    assert await ChatRentalRepository(session).count_active_by_account(acc.id) == 0
