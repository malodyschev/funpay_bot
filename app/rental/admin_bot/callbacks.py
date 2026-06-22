from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix='m'):
    """Верхнее меню: dashboard / lots / rentals."""

    action: str


class Cat(CallbackData, prefix='cat'):
    """Навигация по дереву категорий.

    action: open (показать узел) | add (новая подкатегория) | add_lot (новый лот сюда).
    category_id: id узла; 0 — корень дерева.
    """

    action: str
    category_id: int


class XAddAccount(CallbackData, prefix='xaddacc'):
    """Начать добавление X-аккаунта (логин+пароль+JWT) в лот."""

    lot_id: int


class XAcc(CallbackData, prefix='xacc'):
    """Действие над X-аккаунтом: action=open|creds|code|edit|replace|delete|delete_yes."""

    action: str
    x_account_id: int


class XReplace(CallbackData, prefix='xrepl'):
    """Заменить X-аккаунт old_id на new_id (перенос аренд)."""

    old_id: int
    new_id: int


class XKick(CallbackData, prefix='xkick'):
    """Подтвердить ручной кик истёкшей X-аренды (закрыть)."""

    rental_id: int


class LotOpen(CallbackData, prefix='lot'):
    """Открыть список аккаунтов лота."""

    lot_id: int


class Acc(CallbackData, prefix='a'):
    """Действие над аккаунтом.

    action: open | reveal | sessions | deauth | notes | extend |
            kick | kick_yes | release | offline | banned | banned_yes | activate
    """

    action: str
    account_id: int


class Extend(CallbackData, prefix='ext'):
    """Продлить аренду аккаунта на minutes минут."""

    account_id: int
    minutes: int


class Refund(CallbackData, prefix='rf'):
    """Подтверждение возврата по заказу (yes=1/0)."""

    yes: int
    order_id: str


class AddAccount(CallbackData, prefix='addacc'):
    """Начать загрузку нового аккаунта (maFile) в указанный лот."""

    lot_id: int


class BindAccount(CallbackData, prefix='bindacc'):
    """Начать авто-привязку аутентификатора (логин+пароль+коды) в лот."""

    lot_id: int


class LotAct(CallbackData, prefix='la'):
    """Действие над лотом: action=duration|toggle_active|type_*|category, lot_id."""

    action: str
    lot_id: int


class SetCat(CallbackData, prefix='setcat'):
    """Привязать лот lot_id к категории category_id."""

    lot_id: int
    category_id: int


class MoveTo(CallbackData, prefix='mv'):
    """Переместить аккаунт в другой лот."""

    account_id: int
    lot_id: int
