import html
import math
from datetime import UTC, datetime

from app.rental.common.enums import AccountStatusEnum
from app.rental.models.lot import Lot
from app.rental.services.admin import AccountView, Dashboard, LotStock, RentalView
from app.rental.steam.interface import SteamSessionInfo


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


def fmt_dashboard(dash: Dashboard, lots: list[LotStock]) -> str:
    """Главный экран: счётчики статусов, активные аренды, остатки по лотам."""
    total = sum(dash.status_counts.values())
    lines = ['📊 <b>Дашборд</b>', '']

    if total == 0:
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
            light = '🟢' if ls.free else '🔴'
            tail = ' — нет в наличии ⚠️' if not ls.free else ''
            lines.append(
                f'{light} {html.escape(ls.lot.title)} · <b>{ls.free}</b>/{ls.total}{tail}',
            )
    return '\n'.join(lines)


def fmt_lot(lot: Lot, n_accounts: int) -> str:
    """Шапка лота с конфигурацией (для экрана лота)."""
    kind = '⏱ Продление' if lot.is_extension else '🎮 Аренда'
    status = '🟢 активен' if lot.active else '⚪️ выключен'
    dur = f'{lot.duration_minutes} мин.' + ('' if lot.duration_minutes else ' ⚠️ не задана')
    lines = [
        f'🗂 <b>{html.escape(lot.title)}</b>',
        f'{kind} · {status}',
        f'Длительность: {dur}',
    ]
    if lot.funpay_lot_id:
        lines.append(f'FunPay оффер: <code>{lot.funpay_lot_id}</code>')
    if not lot.is_extension:
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
    """Список активных аренд."""
    if not views:
        return '<b>📋 Активные аренды</b>\n\nНет активных аренд.'
    lines = ['<b>📋 Активные аренды</b>', '']
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
