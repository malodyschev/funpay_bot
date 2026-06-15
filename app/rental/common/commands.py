CODE_COMMANDS = frozenset({'!код', '!code', '/code'})
TIME_COMMANDS = frozenset({'!время', '!time', '/time'})
STOCK_COMMANDS = frozenset({'!наличие', '!stock', '/stock'})
FAQ_COMMANDS = frozenset({'!помощь', '!faq', '/faq', '!help'})

FAQ_TEXT = (
    'Команды:\n'
    '!код — получить текущий код Steam Guard\n'
    '!время — сколько осталось до конца аренды\n'
    '!наличие — сколько свободных аккаунтов\n'
    '!помощь — это сообщение'
)

DEFAULT_DELIVERY_TEMPLATE = (
    'Логин: {login}\n'
    'Пароль: {password}\n'
    'Срок аренды: {minutes} мин.\n'
    'Команды: !код (Steam Guard), !время, !наличие, !помощь'
)
