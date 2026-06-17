from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Menu
from app.rental.services.admin import AdminService
from app.runtime import runtime


router = Router()

_TITLE = '🎮 <b>Админка аренды Steam</b>'


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(_TITLE, reply_markup=kb.main_menu())


@router.callback_query(Menu.filter(F.action == 'menu'))
async def open_menu(cb: CallbackQuery) -> None:
    await cb.message.edit_text(_TITLE, reply_markup=kb.main_menu())
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'dashboard'))
async def dashboard(cb: CallbackQuery) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        dash = await svc.dashboard()
        lots = await svc.lots_with_stock()
    await cb.message.edit_text(fmt.fmt_dashboard(dash, lots), reply_markup=kb.back_to_menu())
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'lots'))
async def lots(cb: CallbackQuery) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        lots = await svc.lots_with_stock()
    text = (
        'Нет лотов. Создай лот через CLI.'
        if not lots
        else (
            '🗂 <b>Лоты</b> — выбери лот:\n'
            '🟢 виден · 🔵 скрыт (все в аренде) · 🔴 скрыт (нет свободных) · ⚪️ выключен'
        )
    )
    await cb.message.edit_text(text, reply_markup=kb.lots_menu(lots))
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'rentals'))
async def rentals(cb: CallbackQuery) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        views = await svc.active_rentals()
    await cb.message.edit_text(fmt.fmt_rentals(views), reply_markup=kb.rentals_list(views))
    await cb.answer()
