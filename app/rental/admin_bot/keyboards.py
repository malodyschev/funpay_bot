from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.rental.admin_bot.callbacks import (
    Acc,
    AddAccount,
    BindAccount,
    Extend,
    LotAct,
    LotOpen,
    Menu,
    MoveTo,
    Refund,
    Sim,
)
from app.rental.admin_bot.formatters import account_button_label, rental_button_label
from app.rental.common.enums import AccountStatusEnum
from app.rental.models.lot import Lot
from app.rental.services.admin import AccountView, LotStock, RentalView


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='📊 Дашборд', callback_data=Menu(action='dashboard'))
    kb.button(text='🗂 Лоты и аккаунты', callback_data=Menu(action='lots'))
    kb.button(text='📋 Активные аренды', callback_data=Menu(action='rentals'))
    kb.button(text='🧪 Симуляция', callback_data=Menu(action='sim'))
    kb.adjust(1)
    return kb.as_markup()


def back_to_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    return kb.as_markup()


def lot_kind() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='🎮 Лот аренды', callback_data=Menu(action='add_lot_rental'))
    kb.button(text='⏱ Лот продления', callback_data=Menu(action='add_lot_ext'))
    kb.button(text='⬅️ Назад', callback_data=Menu(action='lots'))
    kb.adjust(1)
    return kb.as_markup()


def lots_menu(lots: list[LotStock]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ls in lots:
        mark = '' if ls.lot.active else '⚪️ '
        if ls.lot.is_extension:
            label = f'{mark}⏱ {ls.lot.title} (продление)'
        else:
            label = f'{mark}{ls.lot.title} ({ls.free}/{ls.total})'
        kb.button(text=label, callback_data=LotOpen(lot_id=ls.lot.id))
    kb.button(text='🔄 Синхр. с FunPay', callback_data=Menu(action='sync'))
    kb.button(text='➕ Добавить лот', callback_data=Menu(action='add_lot'))
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    kb.adjust(1)
    return kb.as_markup()


def lot_accounts(views: list[AccountView], lot: Lot) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for v in views:
        kb.button(
            text=account_button_label(v),
            callback_data=Acc(action='open', account_id=v.account.id),
        )
    kb.button(
        text=f'⏱ Длительность ({lot.duration_minutes} мин)',
        callback_data=LotAct(action='duration', lot_id=lot.id),
    )
    kb.button(
        text='⚪️ Выключить лот' if lot.active else '🟢 Включить лот',
        callback_data=LotAct(action='toggle_active', lot_id=lot.id),
    )
    if not lot.is_extension:
        kb.button(text='🔑 Привязать (логин+пароль)', callback_data=BindAccount(lot_id=lot.id))
        kb.button(text='📄 Добавить по maFile', callback_data=AddAccount(lot_id=lot.id))
    kb.button(text='⬅️ К лотам', callback_data=Menu(action='lots'))
    kb.adjust(1)
    return kb.as_markup()


def account_card(view: AccountView) -> InlineKeyboardMarkup:
    """Действия зависят от статуса аккаунта."""
    acc = view.account
    kb = InlineKeyboardBuilder()
    kb.button(text='🔐 Показать креды', callback_data=Acc(action='reveal', account_id=acc.id))

    if acc.status == AccountStatusEnum.RENTED:
        kb.button(text='⛔ Досрочный кик', callback_data=Acc(action='kick', account_id=acc.id))
        kb.button(text='⏱ Продлить', callback_data=Acc(action='extend', account_id=acc.id))
        kb.button(
            text='🆓 Освободить (без деавт.)',
            callback_data=Acc(action='release', account_id=acc.id),
        )

    if acc.status not in (AccountStatusEnum.OFFLINE, AccountStatusEnum.BANNED):
        kb.button(text='⚪️ В оффлайн', callback_data=Acc(action='offline', account_id=acc.id))
        kb.button(text='⛔️ Бан', callback_data=Acc(action='banned', account_id=acc.id))
    if acc.status != AccountStatusEnum.FREE:
        kb.button(text='🟢 Вернуть в пул', callback_data=Acc(action='activate', account_id=acc.id))

    if acc.status != AccountStatusEnum.RENTED:
        kb.button(text='🔀 Переместить в лот', callback_data=Acc(action='move', account_id=acc.id))
    kb.button(text='📝 Заметка', callback_data=Acc(action='notes', account_id=acc.id))
    kb.button(text='⬅️ К лоту', callback_data=LotOpen(lot_id=acc.lot_id))
    kb.adjust(1)
    return kb.as_markup()


def move_picker(account_id: int, lots: list[LotStock], current_lot_id: int) -> InlineKeyboardMarkup:
    """Выбор целевого лота для перемещения аккаунта (без лотов-продлений и текущего)."""
    kb = InlineKeyboardBuilder()
    for ls in lots:
        if ls.lot.is_extension or ls.lot.id == current_lot_id:
            continue
        kb.button(
            text=f'{ls.lot.title} ({ls.free}/{ls.total})',
            callback_data=MoveTo(account_id=account_id, lot_id=ls.lot.id),
        )
    kb.button(text='↩️ Отмена', callback_data=Acc(action='open', account_id=account_id))
    kb.adjust(1)
    return kb.as_markup()


def confirm(action: str, account_id: int, label: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(
        text=f'✅ Да, {label}',
        callback_data=Acc(action=f'{action}_yes', account_id=account_id),
    )
    kb.button(text='↩️ Отмена', callback_data=Acc(action='open', account_id=account_id))
    kb.adjust(1)
    return kb.as_markup()


def extend_options(account_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for minutes in (10, 30, 60, 180):
        kb.button(
            text=f'+{minutes} мин',
            callback_data=Extend(account_id=account_id, minutes=minutes),
        )
    kb.button(text='↩️ Назад', callback_data=Acc(action='open', account_id=account_id))
    kb.adjust(2)
    return kb.as_markup()


def rentals_list(views: list[RentalView]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for v in views:
        kb.button(
            text=rental_button_label(v),
            callback_data=Acc(action='open', account_id=v.rental.account_id),
        )
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    kb.adjust(1)
    return kb.as_markup()


def refund_request(order_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='✅ Вернуть', callback_data=Refund(yes=1, order_id=order_id))
    kb.button(text='❌ Отклонить', callback_data=Refund(yes=0, order_id=order_id))
    kb.adjust(2)
    return kb.as_markup()


# ---------- симуляция ----------

def sim_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='🛒 Новый заказ', callback_data=Sim(action='order_menu'))
    kb.button(text='💬 Команда в чат', callback_data=Sim(action='cmd_menu'))
    kb.button(text='⭐ Отзыв (продление)', callback_data=Sim(action='review_menu'))
    kb.button(text='⏰ Истечь сейчас', callback_data=Sim(action='expire_menu'))
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    kb.adjust(1)
    return kb.as_markup()


def sim_pick_lot(lots: list[LotStock]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for ls in lots:
        kb.button(
            text=f'{ls.lot.title} ({ls.free} своб.)',
            callback_data=Sim(action='order', arg=str(ls.lot.id)),
        )
    kb.button(text='⬅️ Назад', callback_data=Menu(action='sim'))
    kb.adjust(1)
    return kb.as_markup()


def sim_pick_rental(views: list[RentalView], action: str) -> InlineKeyboardMarkup:
    """Выбрать активную аренду для cmd/review/expire (arg — order_id или chat_id)."""
    kb = InlineKeyboardBuilder()
    for v in views:
        login = v.account.login if v.account else f'acc#{v.rental.account_id}'
        if action == 'cmd':
            arg = str(v.rental.chat_id)
        else:
            arg = v.rental.funpay_order_id
        kb.button(text=f'🔵 {login}', callback_data=Sim(action=action, arg=arg))
    kb.button(text='⬅️ Назад', callback_data=Menu(action='sim'))
    kb.adjust(1)
    return kb.as_markup()


def sim_commands(chat_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for cmd in ('!free', '!free-all', '!acc', '!code', '!time', '!extend', '!refund', '!admin'):
        kb.button(text=cmd, callback_data=Sim(action='cmd_send', arg=f'{chat_id}|{cmd}'))
    kb.button(text='⬅️ Назад', callback_data=Sim(action='cmd_menu'))
    kb.adjust(2)
    return kb.as_markup()
