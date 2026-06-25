import html
import math
from datetime import UTC, datetime

from app.rental.common.code_log import parse_code_times
from app.rental.common.enums import AccountStatusEnum, FulfillmentEnum, ProviderEnum
from app.rental.models.category import Category
from app.rental.models.chat_account import ChatAccount
from app.rental.models.lot import Lot
from app.rental.services.admin import (
    AccountView,
    CategoryBrowse,
    ChatAccountLoad,
    ChatPoolStat,
    ChatRentalView,
    Dashboard,
    LotStock,
    RentalCounts,
    RentalView,
    Stats,
)
from app.rental.steam.interface import SteamSessionInfo


def fmt_stats(s: Stats) -> str:
    """Экран статистики по арендам."""
    return (
        '📈 <b>Статистика аренд</b>\n\n'
        f'За 24 часа: <b>{s.rentals_24h}</b>\n'
        f'За 7 дней: <b>{s.rentals_7d}</b>\n'
        f'За 30 дней: <b>{s.rentals_30d}</b>\n'
        f'Сейчас активны: <b>{s.active}</b>\n\n'
        '💰 Выручка (примерно, по цене лотов; без учёта продлений):\n'
        f'7 дней: <b>{s.revenue_7d:.0f} ₽</b>\n'
        f'30 дней: <b>{s.revenue_30d:.0f} ₽</b>'
    )


def lot_mark(ls: LotStock) -> str:
    """Индикатор состояния лота (его видимость на FunPay).

    ⚪️ скрыт/выключен · 🟡 автовыдача (видна) · 🟢 аренда видна (есть свободные) ·
    🔵 скрыт — все аккаунты в аренде · 🔴 скрыт — нет свободных аккаунтов.
    """
    if not ls.lot.active:
        return '⚪️'
    if ls.lot.is_autodelivery:
        return '🟡'
    if ls.lot.is_extension or ls.free > 0:
        return '🟢'
    if ls.rented > 0:
        return '🔵'
    return '🔴'


def lot_button_label(ls: LotStock) -> str:
    """Подпись кнопки лота в списке (категория/плоский список)."""
    mark = lot_mark(ls)
    if ls.lot.is_extension:
        return f'{mark} ⏱ {ls.lot.title} (продление)'
    if ls.lot.is_autodelivery:
        return f'{mark} {ls.lot.title} (автовыдача)'
    return f'{mark} {ls.lot.title} ({ls.free}/{ls.total})'


_FULFILLMENT_ICON = {
    FulfillmentEnum.RENTAL: '🎮',
    FulfillmentEnum.AUTODELIVERY: '🟡',
    FulfillmentEnum.OTHER: '🧩',
}
_PROVIDER_LABEL = {ProviderEnum.STEAM: 'Steam', ProviderEnum.CHAT: 'Chat'}


def category_button_label(category: Category) -> str:
    """Подпись кнопки категории. Иконка по своему типу выдачи (если задан явно)."""
    icon = _FULFILLMENT_ICON.get(category.fulfillment, '📁') if category.fulfillment else '📁'
    suffix = '' if category.active else ' ⚪️'
    return f'{icon} {category.title}{suffix}'


def chat_account_button_label(load: ChatAccountLoad) -> str:
    """Подпись кнопки Chat-аккаунта в списке лота (с занятостью слотов)."""
    account = load.account
    code = '🔑' if account.totp_secret_enc else '⚠️ без 2FA'
    return f'🟣 {account.login} · {load.used}/{account.slots} мест · {code}'


def fmt_lot_chat(lot: Lot, loads: list[ChatAccountLoad]) -> str:
    """Шапка Chat-лота (шаренная аренда) с занятостью пула."""
    status = '🟢 активен' if lot.active else '⚪️ выключен'
    dur = f'{lot.duration_minutes} мин.' + ('' if lot.duration_minutes else ' ⚠️ не задана')
    total_slots = sum(load.account.slots for load in loads)
    used = sum(load.used for load in loads)
    lines = [
        f'🟣 <b>{html.escape(lot.title)}</b>',
        f'Chat · шаренная аренда · {status}',
        f'Длительность: {dur}',
        f'Chat-аккаунтов в пуле: {len(loads)}',
        f'Занято мест: <b>{used}</b>/{total_slots} (свободно {max(0, total_slots - used)})',
    ]
    if not lot.active:
        lines.append('\n⚠️ Лот выключен — заказы по нему не обрабатываются.')
    return '\n'.join(lines)


def fmt_chat_account_card(account: ChatAccount, used: int = 0) -> str:
    """Карточка Chat-аккаунта (с занятостью слотов)."""
    free = max(0, account.slots - used)
    return '\n'.join([
        f'🟣 <b>Chat-аккаунт #{account.id}</b> — {html.escape(account.login)}',
        f'Занято: <b>{used}</b>/{account.slots} (свободно {free})',
        f'2FA-ключ: {"есть ✅" if account.totp_secret_enc else "нет ⚠️"}',
    ])


def fmt_category(browse: CategoryBrowse) -> str:
    """Заголовок экрана навигации по категории."""
    node = browse.node
    if node is None:
        return '🗂 <b>Каталог</b>\nВыбери раздел:'
    lines = [f'🗂 <b>{html.escape(node.title)}</b>']
    meta: list[str] = []
    if browse.fulfillment:
        meta.append(f'тип: {browse.fulfillment.value}')
    if browse.provider:
        meta.append(f'провайдер: {_PROVIDER_LABEL.get(browse.provider, browse.provider.value)}')
    if meta:
        lines.append(' · '.join(meta))
    if not browse.children and not browse.lots:
        lines.append('\nПусто. Добавь подкатегорию или лот.')
    return '\n'.join(lines)


def fmt_sessions(sessions: list[SteamSessionInfo]) -> str:
    """Список активных Steam-сессий для админки."""
    if not sessions:
        return '🌐 Активных сессий нет — на аккаунте никто не залогинен.'
    lines = [f'🌐 <b>Активные сессии ({len(sessions)})</b>']
    for s in sessions:
        when = (
            datetime.fromtimestamp(s.last_seen_ts, tz=UTC).strftime('%d.%m %H:%M UTC')
            if s.last_seen_ts
            else '—'
        )
        loc = ', '.join(p for p in (s.country, s.city) if p) or '—'
        lines.append(f'• {html.escape(s.description)} — был(а) {when}, {loc}')
    lines.append('\nℹ️ Одна из них — текущая проверка ботом (создаётся при запросе).')
    return '\n'.join(lines)


_STATUS_EMOJI = {
    AccountStatusEnum.FREE: '🟢',
    AccountStatusEnum.RENTED: '🔵',
    AccountStatusEnum.DEAUTHORIZING: '🟡',
    AccountStatusEnum.OFFLINE: '⚪️',
    AccountStatusEnum.BANNED: '⛔️',
    AccountStatusEnum.ERROR: '🔴',
}

_STATUS_RU = {
    AccountStatusEnum.FREE: 'Свободно',
    AccountStatusEnum.RENTED: 'В аренде',
    AccountStatusEnum.DEAUTHORIZING: 'Деавторизация',
    AccountStatusEnum.OFFLINE: 'Оффлайн',
    AccountStatusEnum.BANNED: 'Бан',
    AccountStatusEnum.ERROR: 'Ошибка',
}

# Порядок вывода статусов на дашборде.
_STATUS_ORDER = (
    AccountStatusEnum.FREE,
    AccountStatusEnum.RENTED,
    AccountStatusEnum.DEAUTHORIZING,
    AccountStatusEnum.ERROR,
    AccountStatusEnum.OFFLINE,
    AccountStatusEnum.BANNED,
)
# Эти статусы показываем всегда, даже если 0.
_STATUS_ALWAYS = (AccountStatusEnum.FREE, AccountStatusEnum.RENTED)

_RULE = '➖➖➖➖➖➖➖➖➖➖'


def status_label(status: AccountStatusEnum) -> str:
    """Эмодзи + русское название статуса."""
    return f'{_STATUS_EMOJI.get(status, "·")} {_STATUS_RU.get(status, status.name)}'


def minutes_left(expires_at: datetime) -> int:
    """Сколько минут осталось до expires_at (не отрицательное)."""
    return max(0, math.ceil((expires_at - datetime.now()).total_seconds() / 60))


def _dt(value: datetime) -> str:
    return value.strftime('%d.%m %H:%M')


def buyer_link(buyer_id: int | None, username: str | None) -> str:
    """Ссылка на профиль покупателя FunPay (если есть id)."""
    name = html.escape(username or 'покупатель')
    if buyer_id:
        return f'<a href="https://funpay.com/users/{buyer_id}/">{name}</a>'
    return name


def _login_lines(times: list[datetime]) -> list[str]:
    """Строки «когда входил в аккаунт» (= запрашивал код) — ВСЕ входы по порядку.

    Если кода ни разу не просили — арендатор, скорее всего, не заходил.
    """
    if not times:
        return ['Вход: код ни разу не запрашивал']
    lines = [f'Входы (запросы кода), всего {len(times)}:']
    lines += [f'  {i}. {_dt(t)}' for i, t in enumerate(times, 1)]
    return lines


def fmt_chat_pools(pools: list[ChatPoolStat]) -> list[str]:
    """Строки секции «Chat-пулы» для дашборда: аккаунтов и занято/всего мест."""
    if not pools:
        return []
    lines = ['', _RULE, '🟣 <b>Chat-пулы</b>']
    for p in pools:
        free = max(0, p.total - p.used)
        mark = '🟢' if free > 0 else '🔴'
        lines.append(
            f'{mark} {html.escape(p.title)} · акк: <b>{p.accounts}</b> · '
            f'мест: <b>{p.used}</b>/{p.total} (свободно {free})',
        )
    return lines


def fmt_dashboard(
    dash: Dashboard,
    lots: list[LotStock],
    chat_pools: list[ChatPoolStat] | None = None,
) -> str:
    """Главный экран: счётчики статусов, активные аренды, остатки по лотам, Chat-пулы."""
    total = sum(dash.status_counts.values())
    chat_pools = chat_pools or []
    lines = ['📊 <b>Дашборд</b>', '']

    if total == 0 and not chat_pools:
        lines.append('Пул пуст. Добавь лот и аккаунты в разделе «🗂 Лоты».')
        return '\n'.join(lines)

    lines.append(f'👤 <b>Аккаунты</b> · всего {total}')
    for status in _STATUS_ORDER:
        count = dash.status_counts.get(status, 0)
        if count or status in _STATUS_ALWAYS:
            lines.append(f'{status_label(status)} — <b>{count}</b>')

    lines += ['', f'📋 <b>Активные аренды</b> — {dash.active_rentals}']

    if lots:
        lines += ['', _RULE, '🗂 <b>Остатки по лотам</b>']
        for ls in lots:
            if ls.lot.is_extension:
                lines.append(f'⏱ {html.escape(ls.lot.title)} — продление')
                continue
            if ls.lot.is_autodelivery:
                mark = '🟡' if ls.lot.active else '⚪️'
                lines.append(f'{mark} {html.escape(ls.lot.title)} — автовыдача')
                continue
            if not ls.lot.active:
                tail = ' — выключен'
            elif ls.free:
                tail = ''
            elif ls.rented:
                tail = ' — всё в аренде (скрыт)'
            else:
                tail = ' — нет в наличии ⚠️'
            lines.append(
                f'{lot_mark(ls)} {html.escape(ls.lot.title)} · <b>{ls.free}</b>/{ls.total}{tail}',
            )

    lines += fmt_chat_pools(chat_pools)
    return '\n'.join(lines)


def fmt_lot(lot: Lot, n_accounts: int) -> str:
    """Шапка лота с конфигурацией (для экрана лота)."""
    if lot.is_autodelivery:
        kind = '🟡 Автовыдача'
    elif lot.is_extension:
        kind = '⏱ Продление'
    else:
        kind = '🎮 Аренда'
    status = '🟢 активен' if lot.active else '⚪️ выключен'
    lines = [
        f'🗂 <b>{html.escape(lot.title)}</b>',
        f'{kind} · {status}',
    ]
    if lot.is_autodelivery:
        lines.append('Бот этот лот не обрабатывает — выдачей занимается FunPay.')
    else:
        dur = f'{lot.duration_minutes} мин.' + ('' if lot.duration_minutes else ' ⚠️ не задана')
        lines.append(f'Длительность: {dur}')
    if lot.funpay_lot_id:
        lines.append(f'FunPay оффер: <code>{lot.funpay_lot_id}</code>')
    if not lot.is_extension and not lot.is_autodelivery:
        lines.append(f'Аккаунтов: {n_accounts}')
    if not lot.active:
        lines.append('\n⚠️ Лот выключен — заказы по нему не обрабатываются.')
    return '\n'.join(lines)


def fmt_account_card(view: AccountView) -> str:
    """Карточка аккаунта со всей доступной информацией."""
    acc = view.account
    lines = [
        f'<b>Аккаунт #{acc.id}</b> — {html.escape(acc.login)}',
        f'Статус: {status_label(acc.status)} · Тип: {acc.type.name}',
    ]
    if view.lot:
        lines.append(f'Лот: {html.escape(view.lot.title)}')
    if acc.steam_id:
        lines.append(f'steam_id: <code>{acc.steam_id}</code>')
    if view.rental:
        r = view.rental
        lines += [
            '',
            '<b>Текущая аренда:</b>',
            f'Покупатель: {buyer_link(r.buyer_id, r.buyer_username)}',
            f'Заказ: <code>{html.escape(r.funpay_order_id)}</code>',
            f'Активирован: {_dt(r.started_at)}',
            f'Истекает: {_dt(r.expires_at)} (через ~{minutes_left(r.expires_at)} мин.)',
        ]
        if r.extended_minutes:
            lines.append(f'Продлено суммарно: +{r.extended_minutes} мин.')
        lines += _login_lines(parse_code_times(r.code_log))
    if acc.notes:
        lines += ['', f'📝 {html.escape(acc.notes)}']
    return '\n'.join(lines)


def account_button_label(view: AccountView) -> str:
    """Подпись кнопки аккаунта в списке лота."""
    acc = view.account
    suffix = ''
    if view.rental:
        suffix = f' · ⏳{minutes_left(view.rental.expires_at)}м'
    return f'{_STATUS_EMOJI.get(acc.status, "·")} {acc.login}{suffix}'


def fmt_rentals(views: list[RentalView]) -> str:
    """Список активных Steam-аренд."""
    if not views:
        return '<b>🎮 Активные аренды Steam</b>\n\nНет активных аренд.'
    lines = ['<b>🎮 Активные аренды Steam</b>', '']
    for v in views:
        login = html.escape(v.account.login) if v.account else f'acc#{v.rental.account_id}'
        lines.append(
            f'🔵 <b>{login}</b> — {buyer_link(v.rental.buyer_id, v.rental.buyer_username)}\n'
            f'   истекает {_dt(v.rental.expires_at)} (~{minutes_left(v.rental.expires_at)} мин.)',
        )
    return '\n'.join(lines)


def rental_button_label(view: RentalView) -> str:
    """Подпись кнопки аренды в списке."""
    login = view.account.login if view.account else f'acc#{view.rental.account_id}'
    return f'🔵 {login} · ⏳{minutes_left(view.rental.expires_at)}м'


def fmt_rentals_root(counts: RentalCounts) -> str:
    """Подменю «Активные аренды»: выбор типа (Steam / Chat) со счётчиками."""
    return (
        '<b>📋 Активные аренды</b>\n\n'
        f'🎮 Steam — <b>{counts.steam}</b>\n'
        f'🟣 Chat — <b>{counts.chat}</b>\n\n'
        'Выбери тип, чтобы посмотреть список.'
    )


def fmt_chat_rentals(views: list[ChatRentalView]) -> str:
    """Список активных Chat-аренд."""
    if not views:
        return '<b>🟣 Активные аренды Chat</b>\n\nНет активных аренд.'
    lines = ['<b>🟣 Активные аренды Chat</b>', '']
    for v in views:
        login = html.escape(v.account.login) if v.account else f'acc#{v.rental.chat_account_id}'
        lines.append(
            f'🟣 <b>{login}</b> — {buyer_link(v.rental.buyer_id, v.rental.buyer_username)}\n'
            f'   истекает {_dt(v.rental.expires_at)} (~{minutes_left(v.rental.expires_at)} мин.)',
        )
    return '\n'.join(lines)


def chat_rental_button_label(view: ChatRentalView) -> str:
    """Подпись кнопки Chat-аренды в списке."""
    login = view.account.login if view.account else f'acc#{view.rental.chat_account_id}'
    return f'🟣 {login} · ⏳{minutes_left(view.rental.expires_at)}м'


def fmt_chat_rental_card(view: ChatRentalView) -> str:
    """Карточка одной Chat-аренды: арендатор, аккаунт, когда входил, срок."""
    r = view.rental
    login = html.escape(view.account.login) if view.account else f'acc#{r.chat_account_id}'
    lines = [
        f'🟣 <b>Аренда Chat #{r.id}</b>',
        f'Покупатель: {buyer_link(r.buyer_id, r.buyer_username)}',
        f'Аккаунт: {login}',
        f'Заказ: <code>{html.escape(r.funpay_order_id)}</code>',
    ]
    if view.lot:
        lines.append(f'Лот: {html.escape(view.lot.title)}')
    lines.append(
        f'Истекает: {_dt(r.expires_at)} (через ~{minutes_left(r.expires_at)} мин.)',
    )
    lines += _login_lines(parse_code_times(r.code_log))
    return '\n'.join(lines)
