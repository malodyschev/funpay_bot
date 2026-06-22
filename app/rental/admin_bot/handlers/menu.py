import asyncio
import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Cat, Menu
from app.rental.funpay.orders import fetch_unconfirmed, format_report
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
    content = format_report(orders).encode('utf-8')
    await message.answer_document(
        BufferedInputFile(content, filename='unconfirmed_orders.txt'),
        caption=f'🧾 Неподтверждённые заказы: {len(orders)}',
    )


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
    """Открыть каталог категорий (корень дерева)."""
    await _show_category(cb, None)


@router.callback_query(Cat.filter(F.action == 'open'))
async def open_category(cb: CallbackQuery, callback_data: Cat) -> None:
    """Открыть узел дерева категорий (0 — корень)."""
    await _show_category(cb, callback_data.category_id or None)


@router.callback_query(Menu.filter(F.action == 'uncategorized'))
async def uncategorized(cb: CallbackQuery) -> None:
    """Бакет синканных лотов без категории — назначить им категорию."""
    async with get_session() as session:
        lots = await AdminService(session, runtime.get_deps()).uncategorized_lots()
    text = (
        '🆕 <b>Неразобранные лоты</b>\n'
        'Синканы с FunPay. Открой лот → «📂 Категория» → выбери, потом задай '
        'длительность/аккаунт и включи.'
        if lots
        else '🆕 Неразобранных лотов нет.'
    )
    await cb.message.edit_text(text, reply_markup=kb.uncategorized_menu(lots))
    await cb.answer()


async def _show_category(cb: CallbackQuery, category_id: int | None) -> None:
    async with get_session() as session:
        browse = await AdminService(session, runtime.get_deps()).browse(category_id)
    await cb.message.edit_text(fmt.fmt_category(browse), reply_markup=kb.category_menu(browse))
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'rentals'))
async def rentals(cb: CallbackQuery) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        views = await svc.active_rentals()
    await cb.message.edit_text(fmt.fmt_rentals(views), reply_markup=kb.rentals_list(views))
    await cb.answer()
