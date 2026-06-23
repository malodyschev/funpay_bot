import asyncio
import html

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message

from app.config import get_settings
from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Cat, Menu
from app.rental.funpay import earnings as earn
from app.rental.funpay.orders import fetch_unconfirmed, format_report
from app.rental.services.admin import AdminService
from app.runtime import runtime


router = Router()


class SellerEarnings(StatesGroup):
    link = State()


_TITLE = '🎮 <b>Админка аренды</b>'


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


@router.message(Command('seller_earnings'))
async def seller_earnings_start(message: Message, state: FSMContext) -> None:
    """Спросить ссылку на продавца, чтобы посчитать его заработок за 2 месяца."""
    await state.set_state(SellerEarnings.link)
    await message.answer(
        '💰 Пришли ссылку на продавца FunPay (профиль /users/&lt;id&gt;/ или оффер) '
        'либо его числовой id — посчитаю заработок за текущий и прошлый месяц.',
    )


@router.message(SellerEarnings.link)
async def seller_earnings_compute(message: Message, state: FSMContext) -> None:
    """Получить ссылку, спарсить отзывы и прислать отчёт по заработку."""
    await state.clear()
    seller = (message.text or '').strip()
    if not seller:
        await message.answer('Пустая ссылка. Запусти /seller_earnings ещё раз.')
        return
    settings = get_settings()
    await message.answer('💰 Считаю заработок по отзывам — это займёт несколько секунд…')
    try:
        result = await asyncio.to_thread(
            earn.calculate_earnings,
            seller,
            golden_key=settings.funpay_golden_key or None,
            user_agent=settings.funpay_user_agent or None,
            proxy_url=settings.proxy_url or None,
        )
    except earn.FunPayEarningsError as exc:
        await message.answer(f'⚠️ {html.escape(str(exc))}')
        return
    except Exception as exc:
        await message.answer(f'⚠️ Не удалось посчитать заработок: {html.escape(str(exc))}')
        return
    await message.answer(
        earn.format_report(result),
        disable_web_page_preview=True,
    )


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
        chat_pools = await svc.chat_pools()
    await cb.message.edit_text(
        fmt.fmt_dashboard(dash, lots, chat_pools), reply_markup=kb.back_to_menu(),
    )
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
    """Подменю активных аренд: Steam и Chat как подкатегории."""
    async with get_session() as session:
        counts = await AdminService(session, runtime.get_deps()).rental_counts()
    await cb.message.edit_text(fmt.fmt_rentals_root(counts), reply_markup=kb.rentals_root(counts))
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'rentals_steam'))
async def rentals_steam(cb: CallbackQuery) -> None:
    async with get_session() as session:
        views = await AdminService(session, runtime.get_deps()).active_rentals()
    await cb.message.edit_text(fmt.fmt_rentals(views), reply_markup=kb.rentals_list(views))
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'rentals_chat'))
async def rentals_chat(cb: CallbackQuery) -> None:
    async with get_session() as session:
        views = await AdminService(session, runtime.get_deps()).active_chat_rentals()
    await cb.message.edit_text(
        fmt.fmt_chat_rentals(views), reply_markup=kb.chat_rentals_list(views),
    )
    await cb.answer()
