CODE_COMMANDS = frozenset({'!code', '!код', '/code'})
ACC_COMMANDS = frozenset({'!acc', '!аккаунт', '!креды', '/acc'})
STOCK_COMMANDS = frozenset({'!free', '!наличие', '!stock', '/free'})
ADMIN_COMMANDS = frozenset({'!admin', '!админ', '/admin'})
EXTEND_COMMANDS = frozenset({'!extend', '!продлить', '/extend'})
TIME_COMMANDS = frozenset({'!time', '!время', '/time'})
FAQ_COMMANDS = frozenset({'!help', '!помощь', '!faq', '/help'})

FAQ_TEXT = (
    'Команды:\n'
    '🔍 !free — проверить наличие свободных аккаунтов\n'
    '🔑 !acc — получить логин и пароль после оплаты\n'
    '📱 !code — получить код Steam Guard\n'
    '👨‍💼 !admin — вызвать администратора\n'
    '♻️ !extend — инструкция по продлению аренды'
)

EXTEND_TEXT = (
    '♻️ Продление аренды:\n'
    'Чтобы добавить время — оплатите лот продления на странице товара, '
    'и время автоматически добавится к вашей текущей аренде.\n'
    'Если лота продления нет или нужна помощь — напишите !admin.'
)

DEFAULT_DELIVERY_TEMPLATE = (
    'Логин: {login}\n'
    'Пароль: {password}\n'
    'Срок аренды: {minutes} мин.\n'
    'Команды: !acc (логин/пароль), !code (Steam Guard), !free, !extend, !admin'
)
