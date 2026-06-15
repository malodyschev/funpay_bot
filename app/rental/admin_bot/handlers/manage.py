import contextlib
from io import BytesIO
from logging import getLogger

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import keyboards as kb
from app.rental.admin_bot.callbacks import AddAccount, Menu
from app.rental.common.commands import DEFAULT_DELIVERY_TEMPLATE
from app.rental.common.exceptions import DuplicateException, SteamModuleError
from app.rental.services.account_loader import AccountLoaderService
from app.rental.services.admin import AdminService
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


# ---------- новый лот ----------

@router.callback_query(Menu.filter(F.action == 'add_lot'))
async def lot_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LotForm.title)
    await cb.message.answer('➕ <b>Новый лот.</b>\nНазвание (точно как на FunPay):')
    await cb.answer()


@router.message(LotForm.title)
async def lot_title(message: Message, state: FSMContext) -> None:
    await state.update_data(title=(message.text or '').strip())
    await state.set_state(LotForm.duration)
    await message.answer('Длительность аренды в минутах (число):')


@router.message(LotForm.duration)
async def lot_duration(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer('Нужно положительное число минут. Попробуй ещё раз:')
        return
    await state.update_data(duration=int(text))
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
    data = await state.get_data()
    await state.clear()
    async with get_session() as session:
        lot = await AdminService(session, runtime.get_deps()).create_lot(
            title=data['title'],
            duration_minutes=data['duration'],
            game=data.get('game'),
            price=data.get('price'),
            template=template,
        )
        lots = await AdminService(session, runtime.get_deps()).lots_with_stock()
    await message.answer(
        f'✅ Лот #{lot.id} «{lot.title}» создан ({lot.duration_minutes} мин.).',
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
            views = await AdminService(session, runtime.get_deps()).accounts_of_lot(lot_id)
    except (SteamModuleError, DuplicateException) as exc:
        await message.answer(f'❌ Не удалось добавить аккаунт: {exc}')
        return
    await message.answer(
        f'✅ Аккаунт #{account.id} ({account.login}) добавлен в лот.',
        reply_markup=kb.lot_accounts(views, lot_id),
    )
