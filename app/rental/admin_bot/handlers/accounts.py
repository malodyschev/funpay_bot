import html
from logging import getLogger

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Acc, Extend, LotOpen
from app.rental.common.enums import AccountStatusEnum
from app.rental.services.admin import AdminService
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()


class NotesForm(StatesGroup):
    waiting_text = State()


async def _render_card(account_id: int) -> tuple[str, InlineKeyboardMarkup] | None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        view = await svc.account_card(account_id)
    if not view:
        return None
    return fmt.fmt_account_card(view), kb.account_card(view)


async def _show_card(cb: CallbackQuery, account_id: int) -> None:
    rendered = await _render_card(account_id)
    if not rendered:
        await cb.answer('Аккаунт не найден', show_alert=True)
        return
    text, markup = rendered
    await cb.message.edit_text(text, reply_markup=markup)


@router.callback_query(LotOpen.filter())
async def open_lot(cb: CallbackQuery, callback_data: LotOpen) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        views = await svc.accounts_of_lot(callback_data.lot_id)
    if not views:
        await cb.message.edit_text(
            'В этом лоте нет аккаунтов.',
            reply_markup=kb.lot_accounts([], callback_data.lot_id),
        )
        await cb.answer()
        return
    title = views[0].lot.title if views[0].lot else 'Лот'
    await cb.message.edit_text(
        f'🗂 <b>{html.escape(title)}</b> — {len(views)} аккаунт(ов):',
        reply_markup=kb.lot_accounts(views, callback_data.lot_id),
    )
    await cb.answer()


@router.callback_query(Acc.filter(F.action == 'open'))
async def open_account(cb: CallbackQuery, callback_data: Acc) -> None:
    await _show_card(cb, callback_data.account_id)
    await cb.answer()


@router.callback_query(Acc.filter(F.action == 'reveal'))
async def reveal(cb: CallbackQuery, callback_data: Acc) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        creds = await svc.reveal_credentials(callback_data.account_id)
    if not creds:
        await cb.answer('Аккаунт не найден', show_alert=True)
        return
    await cb.message.answer(
        '🔐 <b>Креды</b>\n'
        f'Логин: <code>{html.escape(creds.login)}</code>\n'
        f'Пароль: <code>{html.escape(creds.password)}</code>\n'
        f'Guard-код: <code>{creds.code}</code>',
    )
    await cb.answer()


@router.callback_query(Acc.filter(F.action == 'extend'))
async def extend_menu(cb: CallbackQuery, callback_data: Acc) -> None:
    await cb.message.edit_reply_markup(reply_markup=kb.extend_options(callback_data.account_id))
    await cb.answer()


@router.callback_query(Extend.filter())
async def extend_apply(cb: CallbackQuery, callback_data: Extend) -> None:
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        result = await svc.extend(callback_data.account_id, callback_data.minutes)
    await cb.answer(result, show_alert=True)
    await _show_card(cb, callback_data.account_id)


@router.callback_query(Acc.filter(F.action == 'kick'))
async def kick_confirm(cb: CallbackQuery, callback_data: Acc) -> None:
    await cb.message.edit_reply_markup(
        reply_markup=kb.confirm('kick', callback_data.account_id, 'кикнуть'),
    )
    await cb.answer()


@router.callback_query(Acc.filter(F.action == 'banned'))
async def ban_confirm(cb: CallbackQuery, callback_data: Acc) -> None:
    await cb.message.edit_reply_markup(
        reply_markup=kb.confirm('banned', callback_data.account_id, 'забанить'),
    )
    await cb.answer()


_DIRECT_ACTIONS = {'kick_yes', 'release', 'offline', 'banned_yes', 'activate'}


@router.callback_query(Acc.filter(F.action.in_(_DIRECT_ACTIONS)))
async def account_action(cb: CallbackQuery, callback_data: Acc) -> None:
    account_id = callback_data.account_id
    await cb.answer('Выполняю…')
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        if callback_data.action == 'kick_yes':
            result = await svc.kick(account_id)
        elif callback_data.action == 'release':
            result = await svc.free_without_deauth(account_id)
        elif callback_data.action == 'offline':
            result = await svc.set_status(account_id, AccountStatusEnum.OFFLINE)
        elif callback_data.action == 'banned_yes':
            result = await svc.set_status(account_id, AccountStatusEnum.BANNED)
        else:  # activate
            result = await svc.set_status(account_id, AccountStatusEnum.FREE)
    logger.info('admin action %s on account %s: %s', callback_data.action, account_id, result)
    await cb.message.answer(f'✅ {result}')
    await _show_card(cb, account_id)


@router.callback_query(Acc.filter(F.action == 'notes'))
async def notes_start(cb: CallbackQuery, callback_data: Acc, state: FSMContext) -> None:
    await state.set_state(NotesForm.waiting_text)
    await state.update_data(account_id=callback_data.account_id)
    await cb.message.answer('📝 Пришли текст заметки одним сообщением:')
    await cb.answer()


@router.message(NotesForm.waiting_text)
async def notes_save(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    await state.clear()
    account_id = data['account_id']
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        result = await svc.set_notes(account_id, message.text or '')
        view = await svc.account_card(account_id)
    await message.answer(f'✅ {result}')
    if view:
        await message.answer(fmt.fmt_account_card(view), reply_markup=kb.account_card(view))
