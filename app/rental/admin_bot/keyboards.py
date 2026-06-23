from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.rental.admin_bot.callbacks import (
    Acc,
    AddAccount,
    BindAccount,
    Cat,
    ChatAcc,
    ChatAddAccount,
    ChatKick,
    ChatReplace,
    Extend,
    LotAct,
    LotOpen,
    Menu,
    MoveTo,
    Refund,
    SetCat,
)
from app.rental.admin_bot.formatters import (
    account_button_label,
    category_button_label,
    chat_account_button_label,
    chat_rental_button_label,
    lot_button_label,
    rental_button_label,
)
from app.rental.common.enums import AccountStatusEnum
from app.rental.models.chat_account import ChatAccount
from app.rental.models.lot import Lot
from app.rental.services.admin import (
    AccountView,
    CategoryBrowse,
    ChatAccountLoad,
    ChatRentalView,
    LotStock,
    RentalCounts,
    RentalView,
)


def main_menu() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='📊 Дашборд', callback_data=Menu(action='dashboard'))
    kb.button(text='🗂 Лоты и аккаунты', callback_data=Menu(action='lots'))
    kb.button(text='📋 Активные аренды', callback_data=Menu(action='rentals'))
    kb.button(text='📈 Статистика', callback_data=Menu(action='stats'))
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
    """Плоский список всех лотов (вторичный экран — после синка/создания лота)."""
    kb = InlineKeyboardBuilder()
    for ls in lots:
        kb.button(text=lot_button_label(ls), callback_data=LotOpen(lot_id=ls.lot.id))
    kb.button(text='🔄 Синхр. с FunPay', callback_data=Menu(action='sync'))
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    kb.adjust(1)
    return kb.as_markup()


def category_menu(browse: CategoryBrowse) -> InlineKeyboardMarkup:
    """Экран узла дерева: подкатегории + лоты под ним + управление + навигация."""
    kb = InlineKeyboardBuilder()
    for child in browse.children:
        kb.button(
            text=category_button_label(child),
            callback_data=Cat(action='open', category_id=child.id),
        )
    for ls in browse.lots:
        kb.button(text=lot_button_label(ls), callback_data=LotOpen(lot_id=ls.lot.id))

    node = browse.node
    node_id = node.id if node else 0
    # В корне: бакет неразобранных + синхронизация с FunPay.
    if node is None:
        if browse.uncategorized:
            kb.button(
                text=f'🆕 Неразобранные ({browse.uncategorized})',
                callback_data=Menu(action='uncategorized'),
            )
        kb.button(text='🔄 Синхр. с FunPay', callback_data=Menu(action='sync'))
    kb.button(text='➕ Подкатегория', callback_data=Cat(action='add', category_id=node_id))
    # Лот добавляем только в лист (узел без подкатегорий) — лоты живут на листьях.
    if node is not None and not browse.children:
        kb.button(text='➕ Лот сюда', callback_data=Cat(action='add_lot', category_id=node_id))

    if node is None:
        kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    else:
        kb.button(
            text='⬅️ Назад',
            callback_data=Cat(action='open', category_id=node.parent_id or 0),
        )
    kb.adjust(1)
    return kb.as_markup()


def uncategorized_menu(lots: list[LotStock]) -> InlineKeyboardMarkup:
    """Список синканных лотов без категории — выбрать лот, чтобы назначить категорию."""
    kb = InlineKeyboardBuilder()
    for ls in lots:
        kb.button(text=lot_button_label(ls), callback_data=LotOpen(lot_id=ls.lot.id))
    kb.button(text='🔄 Синхр. с FunPay', callback_data=Menu(action='sync'))
    kb.button(text='⬅️ В каталог', callback_data=Menu(action='lots'))
    kb.adjust(1)
    return kb.as_markup()


def category_picker(lot_id: int, paths: list[tuple]) -> InlineKeyboardMarkup:
    """Выбор категории-листа для лота (paths = [(Category, 'путь / …'), …])."""
    kb = InlineKeyboardBuilder()
    for category, label in paths:
        kb.button(text=f'📂 {label}', callback_data=SetCat(lot_id=lot_id, category_id=category.id))
    kb.button(text='⬅️ Назад к лоту', callback_data=LotOpen(lot_id=lot_id))
    kb.adjust(1)
    return kb.as_markup()


def chat_lot_accounts(lot: Lot, loads: list[ChatAccountLoad]) -> InlineKeyboardMarkup:
    """Экран Chat-лота: пул Chat-аккаунтов + добавление логин/пароль (без maFile/bind)."""
    kb = InlineKeyboardBuilder()
    for load in loads:
        kb.button(
            text=chat_account_button_label(load),
            callback_data=ChatAcc(action='open', chat_account_id=load.account.id),
        )
    kb.button(
        text=f'⏱ Длительность ({lot.duration_minutes} мин)',
        callback_data=LotAct(action='duration', lot_id=lot.id),
    )
    kb.button(
        text='⚪️ Выключить лот' if lot.active else '🟢 Включить лот',
        callback_data=LotAct(action='toggle_active', lot_id=lot.id),
    )
    kb.button(
        text='➕ Добавить Chat-аккаунт (логин+пароль)',
        callback_data=ChatAddAccount(lot_id=lot.id),
    )
    kb.button(text='📂 Категория', callback_data=LotAct(action='category', lot_id=lot.id))
    kb.button(
        text='⬅️ К категории',
        callback_data=Cat(action='open', category_id=lot.category_id or 0),
    )
    kb.adjust(1)
    return kb.as_markup()


def chat_account_card(account: ChatAccount) -> InlineKeyboardMarkup:
    """Карточка Chat-аккаунта: креды (почта/пароль/код), правка, замена, удаление."""
    aid = account.id
    kb = InlineKeyboardBuilder()
    kb.button(text='🔐 Получить креды', callback_data=ChatAcc(action='creds', chat_account_id=aid))
    kb.button(
        text='✏️ Обновить 2FA/пароль',
        callback_data=ChatAcc(action='edit', chat_account_id=aid),
    )
    kb.button(
        text=f'📦 Вместимость ({account.slots})',
        callback_data=ChatAcc(action='slots', chat_account_id=aid),
    )
    kb.button(
        text='🔄 Заменить аккаунт',
        callback_data=ChatAcc(action='replace', chat_account_id=aid),
    )
    kb.button(text='🗑 Удалить аккаунт', callback_data=ChatAcc(action='delete', chat_account_id=aid))
    kb.button(
        text='⬅️ К категории',
        callback_data=Cat(action='open', category_id=account.category_id or 0),
    )
    kb.adjust(1)
    return kb.as_markup()


def chat_replace_picker(old_id: int, candidates: list[ChatAccount]) -> InlineKeyboardMarkup:
    """Выбор аккаунта, на который перенести аренды слетевшего."""
    kb = InlineKeyboardBuilder()
    for acc in candidates:
        kb.button(
            text=f'🟣 {acc.login} (slots {acc.slots})',
            callback_data=ChatReplace(old_id=old_id, new_id=acc.id),
        )
    kb.button(text='⬅️ Отмена', callback_data=ChatAcc(action='open', chat_account_id=old_id))
    kb.adjust(1)
    return kb.as_markup()


def chat_kick_button(rental_id: int) -> InlineKeyboardMarkup:
    """Инлайн-кнопка под алертом об истечении Chat-аренды."""
    kb = InlineKeyboardBuilder()
    kb.button(text='✅ Кикнул (закрыть)', callback_data=ChatKick(rental_id=rental_id))
    return kb.as_markup()


def lot_accounts(views: list[AccountView], lot: Lot) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # Внутренности зависят от типа: у автовыдачи внутри ничего нет.
    if not lot.is_extension and not lot.is_autodelivery:
        for v in views:
            kb.button(
                text=account_button_label(v),
                callback_data=Acc(action='open', account_id=v.account.id),
            )
        kb.button(
            text=f'⏱ Длительность ({lot.duration_minutes} мин)',
            callback_data=LotAct(action='duration', lot_id=lot.id),
        )
    elif lot.is_extension:
        kb.button(
            text=f'⏱ Добавляет ({lot.duration_minutes} мин)',
            callback_data=LotAct(action='duration', lot_id=lot.id),
        )
    kb.button(
        text='⚪️ Выключить лот' if lot.active else '🟢 Включить лот',
        callback_data=LotAct(action='toggle_active', lot_id=lot.id),
    )
    # Кнопки смены типа — показываем те, которыми лот сейчас НЕ является.
    current = 'auto' if lot.is_autodelivery else ('ext' if lot.is_extension else 'rental')
    for action, label in (
        ('type_rental', '🎮 Сделать арендой'),
        ('type_ext', '⏱ Сделать продлением'),
        ('type_auto', '🟡 Сделать автовыдачей'),
    ):
        if action != f'type_{current}':
            kb.button(text=label, callback_data=LotAct(action=action, lot_id=lot.id))
    if not lot.is_extension and not lot.is_autodelivery:
        kb.button(text='🔑 Привязать (логин+пароль)', callback_data=BindAccount(lot_id=lot.id))
        kb.button(text='📄 Добавить по maFile', callback_data=AddAccount(lot_id=lot.id))
    kb.button(text='📂 Категория', callback_data=LotAct(action='category', lot_id=lot.id))
    # Назад — в категорию лота (legacy-лоты без категории → корень дерева).
    kb.button(
        text='⬅️ К категории',
        callback_data=Cat(action='open', category_id=lot.category_id or 0),
    )
    kb.adjust(1)
    return kb.as_markup()


def account_card(view: AccountView) -> InlineKeyboardMarkup:
    """Действия зависят от статуса аккаунта."""
    acc = view.account
    kb = InlineKeyboardBuilder()
    kb.button(text='🔐 Показать креды', callback_data=Acc(action='reveal', account_id=acc.id))
    kb.button(text='🌐 Активные сессии', callback_data=Acc(action='sessions', account_id=acc.id))
    kb.button(text='🚪 Сбросить сессии', callback_data=Acc(action='deauth', account_id=acc.id))

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
        if ls.lot.is_extension or ls.lot.is_autodelivery or ls.lot.id == current_lot_id:
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


def rentals_root(counts: RentalCounts) -> InlineKeyboardMarkup:
    """Подменю «Активные аренды»: Steam / Chat как подкатегории."""
    kb = InlineKeyboardBuilder()
    kb.button(text=f'🎮 Steam ({counts.steam})', callback_data=Menu(action='rentals_steam'))
    kb.button(text=f'🟣 Chat ({counts.chat})', callback_data=Menu(action='rentals_chat'))
    kb.button(text='⬅️ В меню', callback_data=Menu(action='menu'))
    kb.adjust(1)
    return kb.as_markup()


def rentals_list(views: list[RentalView]) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    for v in views:
        kb.button(
            text=rental_button_label(v),
            callback_data=Acc(action='open', account_id=v.rental.account_id),
        )
    kb.button(text='⬅️ Назад', callback_data=Menu(action='rentals'))
    kb.adjust(1)
    return kb.as_markup()


def chat_rentals_list(views: list[ChatRentalView]) -> InlineKeyboardMarkup:
    """Список активных Chat-аренд — кнопка ведёт в карточку Chat-аккаунта."""
    kb = InlineKeyboardBuilder()
    for v in views:
        kb.button(
            text=chat_rental_button_label(v),
            callback_data=ChatAcc(action='open', chat_account_id=v.rental.chat_account_id),
        )
    kb.button(text='⬅️ Назад', callback_data=Menu(action='rentals'))
    kb.adjust(1)
    return kb.as_markup()


def refund_request(order_id: str) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text='✅ Вернуть', callback_data=Refund(yes=1, order_id=order_id))
    kb.button(text='❌ Отклонить', callback_data=Refund(yes=0, order_id=order_id))
    kb.adjust(2)
    return kb.as_markup()
