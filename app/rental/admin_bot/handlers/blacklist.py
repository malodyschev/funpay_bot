from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.database import get_session
from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.admin_bot.callbacks import Blk, Menu
from app.rental.services.admin import AdminService
from app.runtime import runtime


router = Router()

_SKIP = '-'


class BlacklistForm(StatesGroup):
    nick = State()


async def _show_list(message_or_cb, edit: bool) -> None:
    async with get_session() as session:
        entries = await AdminService(session, runtime.get_deps()).blocked_buyers()
    text, markup = fmt.fmt_blacklist(entries), kb.blacklist_menu(entries)
    if edit:
        await message_or_cb.message.edit_text(text, reply_markup=markup)
    else:
        await message_or_cb.answer(text, reply_markup=markup)


@router.callback_query(Menu.filter(F.action == 'blacklist'))
async def open_blacklist(cb: CallbackQuery) -> None:
    await _show_list(cb, edit=True)
    await cb.answer()


@router.callback_query(Blk.filter(F.action == 'add'))
async def blacklist_add_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BlacklistForm.nick)
    await cb.message.answer(
        '🚫 Пришли ник покупателя (как на FunPay) для чёрного списка.\n'
        f'Можно с примечанием через «|», напр. <code>vasya | пытался украсть акк</code>.\n'
        f'Регистр и @ не важны. «{_SKIP}» — отмена.',
    )
    await cb.answer()


@router.message(BlacklistForm.nick)
async def blacklist_add_save(message: Message, state: FSMContext) -> None:
    raw = (message.text or '').strip()
    await state.clear()
    if not raw or raw == _SKIP:
        await message.answer('Отменено.')
        await _show_list(message, edit=False)
        return
    nick, _, note = raw.partition('|')
    nick = nick.strip()
    async with get_session() as session:
        svc = AdminService(session, runtime.get_deps())
        added = await svc.add_blocked_buyer(nick, note)
    if added:
        await message.answer(f'✅ <b>{nick}</b> добавлен в чёрный список.')
    else:
        await message.answer('Не добавил: пустой ник или уже в списке.')
    await _show_list(message, edit=False)


@router.callback_query(Blk.filter(F.action == 'del'))
async def blacklist_delete(cb: CallbackQuery, callback_data: Blk) -> None:
    async with get_session() as session:
        await AdminService(session, runtime.get_deps()).remove_blocked_buyer(callback_data.entry_id)
    await cb.answer('Убран из чёрного списка')
    await _show_list(cb, edit=True)
