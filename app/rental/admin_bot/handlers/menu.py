import asyncio
import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Menu
from app.rental.funpay.orders import fetch_unconfirmed
from app.rental.services.admin import AdminService
from app.runtime import runtime


router = Router()

_TITLE = '🎮 <b>Админка аренды Steam</b>'


@router.message(CommandStart())
async def start(message: Message) -> None:
    await message.answer(_TITLE, reply_markup=kb.main_menu())


@router.message(Command('orders'))
async def unconfirmed_orders(message: Message) -> None:
    """Список неподтверждённых заказов (оплачены, ждут подтверждения) — для поддержки."""
    account = runtime.funpay_account
    if account is None:
        await message.answer('FunPay не подключён.')
        return
    await message.answer('🧾 Собираю неподтверждённые заказы…')
    try:
        orders = await asyncio.to_thread(fetch_unconfirmed, account)
    except Exception as exc:
        await message.answer(f'⚠️ Не удалось получить заказы: {html.escape(str(exc))}')
        return
    if not orders:
        await message.answer('✅ Неподтверждённых заказов нет.')
        return
    lines = [
        f'<code>#{html.escape(o.id)}</code> — {html.escape(o.buyer)} — '
        f'{html.escape(o.description[:40])}'
        for o in orders[:50]
    ]
    text = f'🧾 <b>Неподтверждённые заказы ({len(orders)})</b>\n' + '\n'.join(lines)
    if len(orders) > 50:
        text += f'\n… и ещё {len(orders) - 50}'
    await message.answer(text)


@router.message(Command('backup'))
async def backup_now(message: Message) -> None:
    """Сделать бэкап БД прямо сейчас и прислать .sql.gz в этот чат."""
    from app.rental.backup import make_and_send_backup

    await message.answer('🗄 Делаю бэкап…')
    try:
        await make_and_send_backup(message.bot, [message.chat.id])
    except Exception as exc:
        await message.answer(f'⚠️ Бэкап не удался: {html.escape(str(exc))}')


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


@router.callback_query(Menu.filter(F.action == 'stats'))
async def stats(cb: CallbackQuery) -> None:
    async with get_session() as session:
        data = await AdminService(session, runtime.get_deps()).stats()
    await cb.message.edit_text(fmt.fmt_stats(data), reply_markup=kb.back_to_menu())
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
