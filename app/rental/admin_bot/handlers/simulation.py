import random
import time
from logging import getLogger

from aiogram import F, Router
from aiogram.types import CallbackQuery

from app.database import get_session
from app.rental.admin_bot import keyboards as kb
from app.rental.admin_bot.callbacks import Menu, Sim
from app.rental.funpay.events import NewMessageEvent, NewOrderEvent, NewReviewEvent
from app.rental.services.admin import AdminService
from app.rental.services.dispatcher import on_new_message, on_new_order, on_new_review
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()

_SIM_TITLE = (
    '🧪 <b>Симуляция FunPay</b>\n'
    'Подаёт реальные события в боевые сервисы. Ответы «покупателю» придут сюда же.'
)


async def _lots():
    async with get_session() as session:
        return await AdminService(session, runtime.get_deps()).lots_with_stock()


async def _active():
    async with get_session() as session:
        return await AdminService(session, runtime.get_deps()).active_rentals()


@router.callback_query(Menu.filter(F.action == 'sim'))
async def sim_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(_SIM_TITLE, reply_markup=kb.sim_menu())
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'order_menu'))
async def order_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        'Выбери лот для тестового заказа:',
        reply_markup=kb.sim_pick_lot(await _lots()),
    )
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'order'))
async def make_order(cb: CallbackQuery, callback_data: Sim) -> None:
    lots = await _lots()
    lot = next((ls.lot for ls in lots if str(ls.lot.id) == callback_data.arg), None)
    if not lot:
        await cb.answer('Лот не найден', show_alert=True)
        return
    event = NewOrderEvent(
        order_id=f'SIM-{int(time.time())}',
        lot_title=lot.title,
        buyer_id=random.randint(10_000, 99_999),
        buyer_username=f'test_buyer_{random.randint(1, 999)}',
        chat_id=random.randint(100_000, 999_999),
    )
    await cb.answer('Создаю заказ…')
    await on_new_order(event)
    await cb.message.edit_text(
        f'🛒 Тестовый заказ <code>{event.order_id}</code> по лоту "{lot.title}" подан.',
        reply_markup=kb.sim_menu(),
    )


@router.callback_query(Sim.filter(F.action == 'cmd_menu'))
async def cmd_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        'Выбери активную аренду (чат покупателя):',
        reply_markup=kb.sim_pick_rental(await _active(), 'cmd'),
    )
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'cmd'))
async def cmd_pick(cb: CallbackQuery, callback_data: Sim) -> None:
    await cb.message.edit_text(
        f'Команда в чат #{callback_data.arg}:',
        reply_markup=kb.sim_commands(int(callback_data.arg)),
    )
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'cmd_send'))
async def cmd_send(cb: CallbackQuery, callback_data: Sim) -> None:
    chat_id_str, text = callback_data.arg.split('|', 1)
    event = NewMessageEvent(
        chat_id=int(chat_id_str),
        message_id=int(time.time() * 1000) % 2_000_000_000,
        author_id=1,  # не 0 — иначе диспетчер сочтёт сообщение нашим
        text=text,
    )
    await cb.answer(f'Отправляю {text}…')
    await on_new_message(event)


@router.callback_query(Sim.filter(F.action == 'review_menu'))
async def review_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        'Выбери аренду для отзыва (→ автопродление):',
        reply_markup=kb.sim_pick_rental(await _active(), 'review'),
    )
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'review'))
async def make_review(cb: CallbackQuery, callback_data: Sim) -> None:
    await cb.answer('Отзыв оставлен…')
    await on_new_review(NewReviewEvent(order_id=callback_data.arg, rating=5))
    await cb.message.edit_text(
        f'⭐ Отзыв по заказу <code>{callback_data.arg}</code> подан (аренда продлена).',
        reply_markup=kb.sim_menu(),
    )


@router.callback_query(Sim.filter(F.action == 'expire_menu'))
async def expire_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(
        'Выбери аренду, которую истечь сейчас (→ деавторизация):',
        reply_markup=kb.sim_pick_rental(await _active(), 'expire'),
    )
    await cb.answer()


@router.callback_query(Sim.filter(F.action == 'expire'))
async def make_expire(cb: CallbackQuery, callback_data: Sim) -> None:
    from app.rental.repositories.rental import RentalRepository
    from app.rental.services.expire_rental import ExpireRentalService

    async with get_session() as session:
        rental = await RentalRepository(session).get_by_order_id(callback_data.arg)
    if not rental:
        await cb.answer('Аренда не найдена', show_alert=True)
        return
    await cb.answer('Истекаю аренду…')
    async with get_session() as session:
        await ExpireRentalService(session, runtime.get_deps()).handle(rental.id)
    await cb.message.edit_text(
        f'⏰ Аренда заказа <code>{callback_data.arg}</code> истекла (обработана).',
        reply_markup=kb.sim_menu(),
    )
