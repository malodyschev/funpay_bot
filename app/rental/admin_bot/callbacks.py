from aiogram.filters.callback_data import CallbackData


class Menu(CallbackData, prefix='m'):
    """Верхнее меню: dashboard / lots / rentals / sim."""

    action: str


class LotOpen(CallbackData, prefix='lot'):
    """Открыть список аккаунтов лота."""

    lot_id: int


class Acc(CallbackData, prefix='a'):
    """Действие над аккаунтом.

    action: open | reveal | notes | extend |
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


class Sim(CallbackData, prefix='s'):
    """Симуляция FunPay: action=order|cmd|review|expire|menu, arg — id/команда."""

    action: str
    arg: str = ''


class AddAccount(CallbackData, prefix='addacc'):
    """Начать загрузку нового аккаунта (maFile) в указанный лот."""

    lot_id: int


class BindAccount(CallbackData, prefix='bindacc'):
    """Начать авто-привязку аутентификатора (логин+пароль+коды) в лот."""

    lot_id: int


class LotAct(CallbackData, prefix='la'):
    """Действие над лотом: action=duration|toggle_active|toggle_ext, lot_id."""

    action: str
    lot_id: int


class MoveTo(CallbackData, prefix='mv'):
    """Переместить аккаунт в другой лот."""

    account_id: int
    lot_id: int
