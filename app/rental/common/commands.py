# Команды покупателя. Основная форма — латиницей с «!». Русские и слэш-алиасы
# оставлены, чтобы покупатель не промахнулся, НО во всех текстах показываем
# только основную форму, чтобы никто не путался.
ACC_COMMANDS = frozenset({'!acc', '!акк', '!аккаунт', '!креды', '/acc'})
CODE_COMMANDS = frozenset({'!code', '!код', '/code'})
CHAT_CODE_COMMANDS = frozenset({'!chat-code', '!chatcode', '!chat_code', '!чат-код', '/chatcode'})
CHAT_TIME_COMMANDS = frozenset({'!chat-time', '!chattime', '/chattime'})
CHAT_ACC_COMMANDS = frozenset({'!chat-acc', '!chatacc', '!chat-креды', '/chatacc'})
CHAT_REFUND_COMMANDS = frozenset({'!chat-refund', '!chatrefund', '!chat-возврат', '/chatrefund'})
STOCK_COMMANDS = frozenset({'!free', '!фри', '!наличие', '!stock', '/free'})
STOCK_ALL_COMMANDS = frozenset(
    {'!free-all', '!freeall', '!free_all', '!фри-все', '!всё', '!все', '/freeall'},
)
ADMIN_COMMANDS = frozenset({'!admin', '!админ', '/admin'})
REFUND_COMMANDS = frozenset({'!refund', '!возврат', '/refund'})
EXTEND_COMMANDS = frozenset({'!extend', '!продлить', '!какпродлить', '/extend'})
TIME_COMMANDS = frozenset({'!time', '!время', '/time'})
FAQ_COMMANDS = frozenset({'!help', '!помощь', '!faq', '/help'})


def funpay_chat_url(chat_id: int) -> str:
    """Ссылка на чат FunPay (для алерта администратору по команде !admin)."""
    return f'https://funpay.com/chat/?node={chat_id}'


def funpay_lot_url(funpay_lot_id: int) -> str:
    """Ссылка на оффер FunPay (для прямой ссылки на лот продления в !extend)."""
    return f'https://funpay.com/lots/offer?id={funpay_lot_id}'


def funpay_order_url(order_id: str) -> str:
    """Ссылка на страницу заказа FunPay (order_id без '#')."""
    return f'https://funpay.com/orders/{order_id.lstrip("#")}/'


FAQ_TEXT = (
    '⚙️ Команды бота\n'
    '\n'
    '🔍 !free — свободные аккаунты по лоту, который вы открыли\n'
    '🗂 !free-all — наличие сразу по всем лотам\n'
    '🔑 !acc — логин и пароль (после оплаты)\n'
    '📱 !code — код Steam Guard для входа\n'
    '⏳ !time — сколько осталось до конца аренды\n'
    '♻️ !extend — как продлить аренду\n'
    '↩️ !refund — запросить возврат (подтверждает продавец)\n'
    '👨‍💻 !admin — позвать администратора'
)

EXTEND_TEXT = (
    '♻️ Как продлить аренду\n'
    '\n'
    'Чтобы добавить время — оплатите лот продления на странице товара. '
    'Время автоматически прибавится к вашей текущей аренде.\n'
    '\n'
    '💡 Продлевайте заранее, до окончания времени, чтобы не потерять сессию.\n'
    'Нет лота продления или нужна помощь — напишите !admin.'
)

# Сообщение, которое покупатель получает СРАЗУ после оплаты (и повторно по !acc).
# Логин/пароль выдаются сразу, отсчёт времени идёт с момента оплаты.
DEFAULT_DELIVERY_TEMPLATE = (
    '✅ Оплата получена! Приятной игры 🎮\n'
    '\n'
    '🔐 Данные для входа\n'
    '👤 Логин: {login}\n'
    '🔑 Пароль: {password}\n'
    '\n'
    '⏳ Времени аренды: {minutes} мин. Отсчёт идёт с момента оплаты.\n'
    '\n'
    '📋 Команды в этом чате\n'
    '📱 !code — код Steam Guard для входа\n'
    '🔑 !acc — снова показать логин и пароль\n'
    '⏳ !time — сколько осталось времени\n'
    '♻️ !extend — продлить аренду\n'
    '👨‍💻 !admin — позвать администратора\n'
    '\n'
    '🎁 Оставьте отзыв 5★ — добавим час аренды в подарок!'
)

# Сообщение выдачи для X (отдельное от Steam): код входа — TOTP по !chat-code.
CHAT_DELIVERY_TEMPLATE = (
    '✅ Оплата получена!\n'
    '\n'
    '🔐 Данные для входа\n'
    '👤 Логин: {login}\n'
    '🔑 Пароль: {password}\n'
    '\n'
    '⏳ Времени аренды: {minutes} мин. Отсчёт идёт с момента оплаты.\n'
    '\n'
    '📋 Команды в этом чате\n'
    '🔑 !chat-code — получить 2fa код\n'
    '⏳ !time — сколько осталось времени\n'
    '↩️ !refund — запросить возврат\n'
    '👨‍💻 !admin — позвать администратора\n'
    '\n'
    '🎁 Оставьте отзыв 5★ — добавим 1 день аренды в подарок!\n'
    '\n'
    '🔑 Код входа (2FA): отправьте !chat-code'
)
