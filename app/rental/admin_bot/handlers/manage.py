import contextlib
from io import BytesIO
from logging import getLogger

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import AddAccount, LotAct, Menu
from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.common.exceptions import DuplicateException, SteamModuleError
from app.rental.funpay.lot_sync import sync_lots
from app.rental.services.account_loader import AccountLoaderService
from app.rental.services.admin import AdminService
from app.rental.services.lot_visibility import sync_lot_visibility
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()

_SKIP = '-'


class LotForm(StatesGroup):
    title = State()
    duration = State()
    game = State()
    price = State()
    template = State()


class AccountForm(StatesGroup):
    mafile = State()
    password = State()


class LotEditForm(StatesGroup):
    duration = State()


# ---------- синхронизация и конфиг лота ----------

@router.callback_query(Menu.filter(F.action == 'sync'))
async def sync_funpay_lots(cb: CallbackQuery) -> None:
    account = runtime.funpay_account
    if account is None:
        await cb.answer('Доступно только в боевом режиме (нужен golden_key).', show_alert=True)
        return
    await cb.answer('Синхронизирую с FunPay…')
    async with get_session() as session:
        created, updated = await sync_lots(session, account)
        lots = await AdminService(session, runtime.get_deps()).lots_with_stock()
    await cb.message.answer(
        f'🔄 FunPay: создано {created}, обновлено {updated}.\n'
        'Новые лоты выключены — задай длительность, привяжи аккаунт и включи.',
        reply_markup=kb.lots_menu(lots),
    )


@router.callback_query(LotAct.filter(F.action == 'toggle_active'))
async def lot_toggle_active(cb: CallbackQuery, callback_data: LotAct) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        lot = await svc.get_lot(callback_data.lot_id)
        if not lot:
            await cb.answer('Лот не найден', show_alert=True)
            return
        if not lot.active and not lot.is_extension and lot.duration_minutes <= 0:
            await cb.answer('Сначала задай длительность лота.', show_alert=True)
            return
        await svc.toggle_lot_active(callback_data.lot_id)
        lot = await svc.get_lot(callback_data.lot_id)
        views = await svc.accounts_of_lot(callback_data.lot_id)
    await cb.message.edit_text(
        fmt.fmt_lot(lot, len(views)),
        reply_markup=kb.lot_accounts(views, lot),
    )
    await cb.answer('Лот включён' if lot.active else 'Лот выключен')


@router.callback_query(LotAct.filter(F.action == 'duration'))
async def lot_duration_start(cb: CallbackQuery, callback_data: LotAct, state: FSMContext) -> None:
    await state.set_state(LotEditForm.duration)
    await state.update_data(lot_id=callback_data.lot_id)
    await cb.message.answer('Введи длительность аренды в минутах (число):')
    await cb.answer()


@router.message(LotEditForm.duration)
async def lot_duration_set(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer('Нужно положительное число минут. Ещё раз:')
        return
    data = await state.get_data()
    await state.clear()
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        await svc.set_lot_duration(data['lot_id'], int(text))
        lot = await svc.get_lot(data['lot_id'])
        views = await svc.accounts_of_lot(data['lot_id'])
    await message.answer(
        f'✅ Длительность: {int(text)} мин.',
        reply_markup=kb.lot_accounts(views, lot),
    )


# ---------- новый лот ----------

@router.callback_query(Menu.filter(F.action == 'add_lot'))
async def lot_start(cb: CallbackQuery) -> None:
    await cb.message.answer('➕ <b>Новый лот.</b> Выбери тип:', reply_markup=kb.lot_kind())
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'add_lot_rental'))
async def lot_start_rental(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LotForm.title)
    await state.update_data(is_extension=False)
    await cb.message.answer('🎮 <b>Лот аренды.</b>\nНазвание (точно как на FunPay):')
    await cb.answer()


@router.callback_query(Menu.filter(F.action == 'add_lot_ext'))
async def lot_start_ext(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LotForm.title)
    await state.update_data(is_extension=True)
    await cb.message.answer('⏱ <b>Лот продления.</b>\nНазвание (точно как на FunPay):')
    await cb.answer()


@router.message(LotForm.title)
async def lot_title(message: Message, state: FSMContext) -> None:
    data = await state.update_data(title=(message.text or '').strip())
    await state.set_state(LotForm.duration)
    if data.get('is_extension'):
        await message.answer('Сколько минут добавляет это продление (число):')
    else:
        await message.answer('Длительность аренды в минутах (число):')


@router.message(LotForm.duration)
async def lot_duration(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer('Нужно положительное число минут. Попробуй ещё раз:')
        return
    data = await state.update_data(duration=int(text))
    if data.get('is_extension'):
        await _finish_lot(message, state, DEFAULT_DELIVERY_TEMPLATE)
        return
    await state.set_state(LotForm.game)
    await message.answer(f'Игра (или "{_SKIP}" чтобы пропустить):')


@router.message(LotForm.game)
async def lot_game(message: Message, state: FSMContext) -> None:
    game = (message.text or '').strip()
    await state.update_data(game=None if game == _SKIP else game)
    await state.set_state(LotForm.price)
    await message.answer(f'Цена в рублях (число) или "{_SKIP}":')


@router.message(LotForm.price)
async def lot_price(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    price = None
    if text != _SKIP:
        try:
            price = float(text.replace(',', '.'))
        except ValueError:
            await message.answer(f'Не похоже на число. Цена или "{_SKIP}":')
            return
    await state.update_data(price=price)
    await state.set_state(LotForm.template)
    await message.answer(
        'Шаблон выдачи (плейсхолдеры {login} {password} {minutes} {game})\n'
        f'или "{_SKIP}" — взять стандартный:',
    )


@router.message(LotForm.template)
async def lot_template(message: Message, state: FSMContext) -> None:
    text = message.text or ''
    template = DEFAULT_DELIVERY_TEMPLATE if text.strip() == _SKIP else text
    await _finish_lot(message, state, template)


async def _finish_lot(message: Message, state: FSMContext, template: str) -> None:
    """Создать лот из накопленных в FSM данных и показать список лотов."""
    data = await state.get_data()
    await state.clear()
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        lot = await svc.create_lot(
            title=data['title'],
            duration_minutes=data['duration'],
            game=data.get('game'),
            price=data.get('price'),
            template=template,
            is_extension=data.get('is_extension', False),
        )
        lots = await svc.lots_with_stock()
    kind = 'продление' if lot.is_extension else 'аренда'
    await message.answer(
        f'✅ Лот #{lot.id} «{lot.title}» ({kind}, {lot.duration_minutes} мин.) создан.',
        reply_markup=kb.lots_menu(lots),
    )


# ---------- новый аккаунт (maFile) ----------

@router.callback_query(AddAccount.filter())
async def account_start(cb: CallbackQuery, callback_data: AddAccount, state: FSMContext) -> None:
    await state.set_state(AccountForm.mafile)
    await state.update_data(lot_id=callback_data.lot_id)
    await cb.message.answer(
        '➕ <b>Новый аккаунт.</b>\nПришли файл <code>.maFile</code> документом.\n'
        '⚠️ Файл пройдёт через серверы Telegram — после загрузки я удалю сообщение.',
    )
    await cb.answer()


@router.message(AccountForm.mafile, F.document)
async def account_mafile(message: Message, state: FSMContext) -> None:
    buffer = BytesIO()
    await message.bot.download(message.document, destination=buffer)
    try:
        raw = buffer.getvalue().decode('utf-8')
    except UnicodeDecodeError:
        await message.answer('Это не похоже на текстовый maFile. Пришли корректный файл:')
        return
    await state.update_data(raw=raw)
    await state.set_state(AccountForm.password)
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()  # убираем maFile из чата
    await message.answer('maFile получен. Теперь пришли <b>пароль Steam</b> одним сообщением:')


@router.message(AccountForm.mafile)
async def account_mafile_not_document(message: Message) -> None:
    await message.answer('Нужен именно файл .maFile (как документ), а не текст.')


@router.message(AccountForm.password)
async def account_password(message: Message, state: FSMContext) -> None:
    password = message.text or ''
    data = await state.get_data()
    await state.clear()
    lot_id = data['lot_id']
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()  # убираем пароль из чата
    try:
        async with get_session() as session:
            account = await AccountLoaderService(session).load_from_mafile(
                raw_mafile=data['raw'],
                password=password,
                lot_id=lot_id,
            )
            svc = AdminService(session, runtime.get_deps())
            views = await svc.accounts_of_lot(lot_id)
            lot = await svc.get_lot(lot_id)
            await sync_lot_visibility(session, runtime.get_deps(), lot_id)
    except (SteamModuleError, DuplicateException) as exc:
        await message.answer(f'❌ Не удалось добавить аккаунт: {exc}')
        return
    await message.answer(
        f'✅ Аккаунт #{account.id} ({account.login}) добавлен в лот.',
        reply_markup=kb.lot_accounts(views, lot),
    )
