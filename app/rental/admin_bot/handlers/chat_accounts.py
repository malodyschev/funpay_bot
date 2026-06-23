import contextlib
import html
from logging import getLogger

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import ChatAcc, ChatAddAccount, ChatKick, ChatReplace
from app.rental.admin_bot.views import lot_screen
from app.rental.services.admin import AdminService
from app.rental.services.chat_rental import ChatRentalService
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()

_SKIP = '-'


class ChatAccountForm(StatesGroup):
    login = State()
    password = State()
    totp = State()
    slots = State()


class ChatEditForm(StatesGroup):
    totp = State()
    password = State()


# ---------- добавление Chat-аккаунта ----------

@router.callback_query(ChatAddAccount.filter())
async def chat_add_start(
    cb: CallbackQuery, callback_data: ChatAddAccount, state: FSMContext,
) -> None:
    await state.set_state(ChatAccountForm.login)
    await state.update_data(lot_id=callback_data.lot_id)
    await cb.message.answer('🟣 <b>Новый Chat-аккаунт.</b>\nЛогин (email):')
    await cb.answer()


@router.message(ChatAccountForm.login)
async def chat_add_login(message: Message, state: FSMContext) -> None:
    await state.update_data(login=(message.text or '').strip())
    await state.set_state(ChatAccountForm.password)
    await message.answer('Пароль одним сообщением (удалю после получения):')


@router.message(ChatAccountForm.password)
async def chat_add_password(message: Message, state: FSMContext) -> None:
    await state.update_data(password=message.text or '')
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await state.set_state(ChatAccountForm.totp)
    await message.answer(
        f'2FA-ключ (base32-секрет TOTP) или «{_SKIP}» — пока без него.\n'
        'Удалю сообщение после получения:',
    )


@router.message(ChatAccountForm.totp)
async def chat_add_totp(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    await state.update_data(totp=None if text == _SKIP else text)
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await state.set_state(ChatAccountForm.slots)
    await message.answer('Вместимость — сколько человек одновременно (число, напр. 50):')


@router.message(ChatAccountForm.slots)
async def chat_add_slots(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer('Нужно положительное число. Ещё раз:')
        return
    data = await state.get_data()
    await state.clear()
    lot_id = data['lot_id']
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        lot = await svc.get_lot(lot_id)
        if not lot or lot.category_id is None:
            await message.answer('У лота не задана категория — Chat-аккаунт привязывать некуда.')
            return
        account = await svc.create_chat_account(
            category_id=lot.category_id,
            login=data['login'],
            password=data['password'],
            totp_secret=data.get('totp'),
            slots=int(text),
        )
        screen = await lot_screen(svc, lot)
    await message.answer(
        f'✅ Chat-аккаунт #{account.id} ({account.login}) добавлен в пул категории.',
    )
    text_, markup = screen
    await message.answer(text_, reply_markup=markup)


# ---------- карточка Chat-аккаунта ----------

async def _show_card(cb: CallbackQuery, chat_account_id: int) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        account = await svc.get_chat_account(chat_account_id)
        used = await svc.chat_account_load(chat_account_id) if account else 0
    if not account:
        await cb.answer('Аккаунт не найден', show_alert=True)
        return
    await cb.message.edit_text(
        fmt.fmt_chat_account_card(account, used),
        reply_markup=kb.chat_account_card(account),
    )


@router.callback_query(ChatAcc.filter(F.action == 'open'))
async def chat_open(cb: CallbackQuery, callback_data: ChatAcc) -> None:
    await _show_card(cb, callback_data.chat_account_id)
    await cb.answer()


@router.callback_query(ChatAcc.filter(F.action == 'creds'))
async def chat_creds(cb: CallbackQuery, callback_data: ChatAcc) -> None:
    async with get_session() as session:
        creds = await AdminService(session, runtime.get_deps()).chat_account_creds(
            callback_data.chat_account_id,
        )
    if not creds:
        await cb.answer('Аккаунт не найден', show_alert=True)
        return
    await cb.message.answer(
        '🔐 <b>Креды Chat</b>\n'
        f'Почта: <code>{html.escape(creds.login)}</code>\n'
        f'Пароль: <code>{html.escape(creds.password)}</code>\n'
        f'Код 2FA: <code>{creds.code}</code>',
    )
    await cb.answer()


# ---------- обновление 2FA/пароля ----------

@router.callback_query(ChatAcc.filter(F.action == 'edit'))
async def chat_edit_start(cb: CallbackQuery, callback_data: ChatAcc, state: FSMContext) -> None:
    await state.set_state(ChatEditForm.totp)
    await state.update_data(chat_account_id=callback_data.chat_account_id)
    await cb.message.answer(
        f'✏️ Новый 2FA-ключ (base32) или «{_SKIP}» — не менять. Удалю сообщение:',
    )
    await cb.answer()


@router.message(ChatEditForm.totp)
async def chat_edit_totp(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    await state.update_data(totp=None if text == _SKIP else text)
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    await state.set_state(ChatEditForm.password)
    await message.answer(f'Новый пароль или «{_SKIP}» — не менять. Удалю сообщение:')


@router.message(ChatEditForm.password)
async def chat_edit_password(message: Message, state: FSMContext) -> None:
    text = (message.text or '').strip()
    data = await state.get_data()
    await state.clear()
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        await svc.update_chat_account(
            data['chat_account_id'],
            totp_secret=data.get('totp'),
            password=None if text == _SKIP else text,
        )
        account = await svc.get_chat_account(data['chat_account_id'])
        used = await svc.chat_account_load(data['chat_account_id']) if account else 0
    await message.answer('✅ Обновлено.')
    if account:
        await message.answer(
            fmt.fmt_chat_account_card(account, used),
            reply_markup=kb.chat_account_card(account),
        )


# ---------- замена аккаунта ----------

@router.callback_query(ChatAcc.filter(F.action == 'replace'))
async def chat_replace_pick(cb: CallbackQuery, callback_data: ChatAcc) -> None:
    async with get_session() as session:
        candidates = await AdminService(session, runtime.get_deps()).chat_replace_candidates(
            callback_data.chat_account_id,
        )
    if not candidates:
        await cb.answer('Нет аккаунтов с достаточным числом слотов в пуле.', show_alert=True)
        return
    await cb.message.edit_reply_markup(
        reply_markup=kb.chat_replace_picker(callback_data.chat_account_id, candidates),
    )
    await cb.answer()


@router.callback_query(ChatReplace.filter())
async def chat_replace_apply(cb: CallbackQuery, callback_data: ChatReplace) -> None:
    await cb.answer('Переношу аренды…')
    async with get_session() as session:
        result = await ChatRentalService(session, runtime.get_deps()).replace_account(
            callback_data.old_id, callback_data.new_id,
        )
    if not result.ok:
        await cb.message.answer(f'❌ Замена не удалась: {result.reason}')
        return
    await cb.message.answer(
        f'✅ Аккаунт заменён. Перенесено аренд: {result.moved}. '
        'Каждому отправлены новые креды в FunPay.',
    )


# ---------- ручной кик истёкшей аренды ----------

@router.callback_query(ChatKick.filter())
async def chat_kick(cb: CallbackQuery, callback_data: ChatKick) -> None:
    async with get_session() as session:
        ok = await ChatRentalService(session, runtime.get_deps()).kick(callback_data.rental_id)
    await cb.answer('Закрыто' if ok else 'Аренда не найдена')
    with contextlib.suppress(TelegramBadRequest):
        await cb.message.edit_reply_markup(reply_markup=None)


@router.callback_query(ChatAcc.filter(F.action == 'delete'))
async def chat_delete_confirm(cb: CallbackQuery, callback_data: ChatAcc) -> None:
    await cb.message.edit_reply_markup(reply_markup=_confirm_delete(callback_data.chat_account_id))
    await cb.answer()


@router.callback_query(ChatAcc.filter(F.action == 'delete_yes'))
async def chat_delete(cb: CallbackQuery, callback_data: ChatAcc) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        account = await svc.get_chat_account(callback_data.chat_account_id)
        category_id = account.category_id if account else None
        if account:
            await svc.delete_chat_account(callback_data.chat_account_id)
        browse = await svc.browse(category_id) if category_id else None
    await cb.answer('Удалён')
    if browse:
        await cb.message.edit_text(
            fmt.fmt_category(browse),
            reply_markup=kb.category_menu(browse),
        )


def _confirm_delete(aid: int) -> InlineKeyboardMarkup:
    kb_ = InlineKeyboardBuilder()
    kb_.button(
        text='🗑 Да, удалить',
        callback_data=ChatAcc(action='delete_yes', chat_account_id=aid),
    )
    kb_.button(text='⬅️ Отмена', callback_data=ChatAcc(action='open', chat_account_id=aid))
    kb_.adjust(1)
    return kb_.as_markup()
