"""Подсчёт заработка продавца FunPay по отзывам за последние 2 месяца.

FunPay отдаёт дату отзыва лишь с точностью до месяца («В этом месяце»,
«Месяц назад», «3 месяца назад», «Год назад»), поэтому окно считаем в месяцах:
текущий (months_ago=0) и предыдущий (months_ago=1). Источник цифр — суммы,
указанные в тексте отзывов.

Функция синхронная (requests) — из async-хендлера вызывать через
asyncio.to_thread, как fetch_unconfirmed.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from logging import getLogger

import requests
from bs4 import BeautifulSoup


logger = getLogger(__name__)

REVIEWS_URL = 'https://funpay.com/users/reviews'
MAX_PAGES = 200
# Окно подсчёта: текущий месяц (0) и предыдущий (1).
WINDOW_MONTHS = 2

_DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
    'AppleWebKit/537.36 (KHTML, like Gecko) '
    'Chrome/147.0.0.0 Safari/537.36'
)

# Число (с возможным разделителем тысяч-пробелом и дробной частью) + валюта.
PRICE_RE = re.compile(r'([0-9][0-9\s ]*(?:[.,][0-9]+)?)\s*([₽€$])')
USER_ID_RE = re.compile(r'/users/(\d+)/')
OFFER_RE = re.compile(r'lots/offer')

UNKNOWN_CATEGORY = 'Прочее'

# Категория -> ключевые слова (в нижнем регистре), которые ищем в тексте отзыва.
# Порядок важен: первая категория с совпадением и побеждает, поэтому более
# специфичные/узкие ключи лучше держать выше широких.
CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    'Dota 2': ('dota', 'дота', 'дотка'),
    'CS2 / CS:GO': ('cs2', 'cs:go', 'csgo', 'counter-strike', 'контра', 'кс го', 'кс2'),
    'Valorant': ('valorant', 'валорант', 'валик'),
    'ChatGPT / OpenAI': ('chatgpt', 'chat gpt', 'openai', 'gpt-4', 'gpt4', 'чат гпт', 'чатгпт'),
    'Genshin Impact': ('genshin', 'геншин'),
    'Brawl Stars': ('brawl', 'бравл'),
    'Clash of Clans / Royale': ('clash of clans', 'clash royale', 'клеш', 'клэш'),
    'Supercell': ('supercell', 'суперселл'),
    'Fortnite': ('fortnite', 'фортнайт', 'фортнаит'),
    'PUBG': ('pubg', 'пубг', 'пабг'),
    'Roblox': ('roblox', 'роблокс', 'робукс', 'robux'),
    'Minecraft': ('minecraft', 'майнкрафт', 'майн'),
    'Steam': ('steam', 'стим'),
    'Telegram Premium': ('telegram', 'телеграм', 'телега'),
    'Discord': ('discord', 'дискорд', 'nitro', 'нитро'),
    'Spotify': ('spotify', 'спотифай'),
    'YouTube Premium': ('youtube', 'ютуб'),
    'Netflix': ('netflix', 'нетфликс'),
    'World of Tanks': ('world of tanks', 'wot', 'танки', 'танков'),
    'League of Legends': ('league of legends', 'лига легенд'),
    'Mobile Legends': ('mobile legends', 'мобайл легендс', 'млбб', 'mlbb'),
    'Standoff 2': ('standoff', 'стандофф', 'стандоф'),
}


class FunPayEarningsError(RuntimeError):
    """Понятная ошибка парсинга заработка (показываем админу как есть)."""


@dataclass(frozen=True)
class Review:
    detail: str
    date_label: str
    months_ago: int | None
    amount: Decimal | None
    currency: str | None
    category: str = UNKNOWN_CATEGORY


@dataclass
class EarningsResult:
    user_id: str
    profile_url: str
    total_reviews: int
    # months_ago -> {валюта -> сумма}
    by_month: dict[int, dict[str, Decimal]] = field(default_factory=dict)
    counts_by_month: dict[int, int] = field(default_factory=dict)
    # months_ago -> категория -> {валюта -> сумма}
    by_month_category: dict[int, dict[str, dict[str, Decimal]]] = field(default_factory=dict)
    # months_ago -> категория -> количество отзывов
    counts_by_month_category: dict[int, dict[str, int]] = field(default_factory=dict)

    @property
    def this_month(self) -> dict[str, Decimal]:
        """Заработок за текущий месяц («В этом месяце»)."""
        return self.by_month.get(0, {})

    @property
    def previous_month(self) -> dict[str, Decimal]:
        """Заработок за предыдущий месяц («Месяц назад»)."""
        return self.by_month.get(1, {})

    def window_total(self) -> dict[str, Decimal]:
        """Суммарный заработок за окно (текущий + предыдущий месяц), по валютам."""
        total: dict[str, Decimal] = {}
        for bucket in range(WINDOW_MONTHS):
            for currency, amount in self.by_month.get(bucket, {}).items():
                total[currency] = total.get(currency, Decimal(0)) + amount
        return total

    def window_reviews(self) -> int:
        """Сколько отзывов учтено в окне (текущий + предыдущий месяц)."""
        return sum(self.counts_by_month.get(bucket, 0) for bucket in range(WINDOW_MONTHS))

    def category_totals(self) -> dict[str, dict[str, Decimal]]:
        """Сумма по категориям за окно: {категория -> {валюта -> сумма}}.

        Отсортировано по убыванию суммы в рублях (затем по прочим валютам).
        """
        totals: dict[str, dict[str, Decimal]] = {}
        for bucket in range(WINDOW_MONTHS):
            for category, per_currency in self.by_month_category.get(bucket, {}).items():
                dest = totals.setdefault(category, {})
                for currency, amount in per_currency.items():
                    dest[currency] = dest.get(currency, Decimal(0)) + amount
        return dict(
            sorted(totals.items(), key=lambda kv: _money_sort_key(kv[1]), reverse=True),
        )

    def category_counts(self) -> dict[str, int]:
        """Количество отзывов по категориям за окно."""
        counts: dict[str, int] = {}
        for bucket in range(WINDOW_MONTHS):
            for category, count in self.counts_by_month_category.get(bucket, {}).items():
                counts[category] = counts.get(category, 0) + count
        return counts


def calculate_earnings(
    seller: str,
    *,
    golden_key: str | None = None,
    user_agent: str | None = None,
    proxy_url: str | None = None,
    cookie: str | None = None,
    max_pages: int = MAX_PAGES,
) -> EarningsResult:
    """Посчитать заработок продавца FunPay за окно (текущий + предыдущий месяц).

    seller — ссылка на продавца (профиль /users/<id>/ или оффер /lots/offer?id=…)
    либо просто числовой id. Авторизация для публичных отзывов не нужна, но
    golden_key/cookie и proxy можно передать (берём из настроек бота).
    """
    session = requests.Session()
    if proxy_url:
        session.proxies.update({'http': proxy_url, 'https': proxy_url})
    headers = _build_headers(_resolve_cookie(cookie, golden_key), user_agent)

    user_id = _resolve_user_id(seller, session, headers)
    profile_url = f'https://funpay.com/users/{user_id}/'

    reviews = _fetch_reviews_window(session, headers, user_id, max_pages)

    result = EarningsResult(
        user_id=user_id,
        profile_url=profile_url,
        total_reviews=len(reviews),
    )
    for review in reviews:
        bucket = review.months_ago
        # Берём только окно: текущий (0) и предыдущий (1) месяц.
        if bucket is None or bucket >= WINDOW_MONTHS:
            continue
        result.counts_by_month[bucket] = result.counts_by_month.get(bucket, 0) + 1
        cat_counts = result.counts_by_month_category.setdefault(bucket, {})
        cat_counts[review.category] = cat_counts.get(review.category, 0) + 1
        if review.amount is None or review.currency is None:
            continue
        per_currency = result.by_month.setdefault(bucket, {})
        per_currency[review.currency] = (
            per_currency.get(review.currency, Decimal(0)) + review.amount
        )
        cat_currency = result.by_month_category.setdefault(bucket, {}).setdefault(
            review.category, {},
        )
        cat_currency[review.currency] = (
            cat_currency.get(review.currency, Decimal(0)) + review.amount
        )

    return result


def format_report(result: EarningsResult) -> str:
    """Отчёт для Telegram (HTML): общая сумма за 2 месяца + разбивка по категориям."""
    lines = [
        '💰 <b>Заработок продавца</b>',
        f'<a href="{result.profile_url}">{result.profile_url}</a>',
        f'Учтено отзывов за 2 мес.: {result.window_reviews()}',
        '',
        f'Текущий месяц: <b>{_format_money(result.this_month)}</b>',
        f'Прошлый месяц: <b>{_format_money(result.previous_month)}</b>',
        f'Итого за 2 месяца: <b>{_format_money(result.window_total())}</b>',
    ]

    totals = result.category_totals()
    if totals:
        counts = result.category_counts()
        lines += ['', '📂 <b>По категориям (2 месяца):</b>']
        for category, amounts in totals.items():
            count = counts.get(category, 0)
            lines.append(f'• {category}: <b>{_format_money(amounts)}</b> ({count} отз.)')

    return '\n'.join(lines)


def _resolve_cookie(cookie: str | None, golden_key: str | None) -> str | None:
    if cookie:
        return cookie
    if golden_key:
        return f'golden_key={golden_key}'
    return None


def _build_headers(cookie: str | None, user_agent: str | None) -> dict[str, str]:
    headers = {
        'User-Agent': user_agent or _DEFAULT_USER_AGENT,
        'Origin': 'https://funpay.com',
        'Referer': 'https://funpay.com/',
        'X-Requested-With': 'XMLHttpRequest',
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
    }
    if cookie:
        headers['Cookie'] = cookie
    return headers


def _resolve_user_id(
    seller: str,
    session: requests.Session,
    headers: dict[str, str],
) -> str:
    seller = seller.strip()

    if seller.isdigit():
        return seller

    match = USER_ID_RE.search(seller)
    if match:
        return match.group(1)

    if OFFER_RE.search(seller):
        html = _get(session, seller, headers)
        offer_match = USER_ID_RE.search(html)
        if offer_match:
            return offer_match.group(1)
        raise FunPayEarningsError(
            'Не нашёл продавца на странице оффера. '
            'Проверь ссылку или передай профиль /users/<id>/.',
        )

    raise FunPayEarningsError(
        'Не понял, что за продавец. Пришли ссылку на профиль '
        '(https://funpay.com/users/<id>/), на оффер или числовой id.',
    )


def _fetch_reviews_window(
    session: requests.Session,
    headers: dict[str, str],
    user_id: str,
    max_pages: int,
) -> list[Review]:
    """Отзывы продавца с ранней остановкой: листаем, пока не вышли за окно.

    Отзывы идут от новых к старым, поэтому как только встречаем отзыв старше
    окна (months_ago >= WINDOW_MONTHS) — дальше листать смысла нет.
    """
    profile_url = f'https://funpay.com/users/{user_id}/'
    html = _get(session, profile_url, headers)
    _raise_if_blocked(html)

    reviews, continue_token = _parse_reviews_html(html)
    if _reached_window_end(reviews):
        return reviews

    seen_tokens: set[str] = set()
    page = 1

    while continue_token and continue_token not in seen_tokens and page < max_pages:
        seen_tokens.add(continue_token)
        page += 1

        chunk_html = _post(
            session,
            REVIEWS_URL,
            headers,
            data={'user_id': user_id, 'continue': continue_token, 'filter': ''},
        )
        _raise_if_blocked(chunk_html)
        chunk_reviews, next_token = _parse_reviews_html(chunk_html)
        if not chunk_reviews:
            break

        reviews.extend(chunk_reviews)
        if _reached_window_end(chunk_reviews):
            break
        if next_token == continue_token:
            break
        continue_token = next_token
        time.sleep(0.4)

    return reviews


def _reached_window_end(reviews: list[Review]) -> bool:
    """Среди отзывов уже есть хотя бы один старше окна — значит окно пройдено."""
    return any(r.months_ago is not None and r.months_ago >= WINDOW_MONTHS for r in reviews)


def _parse_reviews_html(html: str) -> tuple[list[Review], str | None]:
    soup = BeautifulSoup(html, 'html.parser')

    reviews: list[Review] = []
    for item in soup.select('.review-item'):
        detail_el = item.select_one('.review-item-detail')
        if detail_el is None:
            continue
        detail = _clean_text(detail_el.get_text(' ', strip=True))

        date_el = item.select_one('.review-item-date')
        date_label = _clean_text(date_el.get_text(' ', strip=True)) if date_el else ''

        amount, currency = _extract_price(detail)
        reviews.append(
            Review(
                detail=detail,
                date_label=date_label,
                months_ago=_months_ago_from_label(date_label),
                amount=amount,
                currency=currency,
                category=_detect_category(detail),
            ),
        )

    continue_input = soup.select_one('form.dyn-table-form input[name="continue"]')
    continue_token = continue_input.get('value') if continue_input else None
    return reviews, continue_token


def _extract_price(detail: str) -> tuple[Decimal | None, str | None]:
    matches = PRICE_RE.findall(detail)
    if not matches:
        return None, None

    raw_amount, currency = matches[-1]
    cleaned = raw_amount.replace(' ', '').replace(' ', '').replace(',', '.')
    try:
        return Decimal(cleaned), currency
    except InvalidOperation:
        return None, currency


def _detect_category(detail: str) -> str:
    """Определить категорию товара по тексту отзыва (первое совпадение ключа)."""
    text = detail.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        if any(keyword in text for keyword in keywords):
            return category
    return UNKNOWN_CATEGORY


def _money_sort_key(amounts: dict[str, Decimal]) -> tuple[Decimal, Decimal]:
    """Ключ сортировки категорий: сначала по рублям, затем по сумме прочих валют."""
    rub = amounts.get('₽', Decimal(0))
    other = sum(
        (amount for currency, amount in amounts.items() if currency != '₽'),
        Decimal(0),
    )
    return rub, other


def _months_ago_from_label(label: str) -> int | None:
    text = label.lower().strip()
    if not text:
        return None

    # «В этом месяце» и любые более мелкие сроки -> текущий месяц.
    if (
        'этом месяце' in text
        or 'сегодня' in text
        or 'вчера' in text
        or 'минут' in text
        or 'час' in text
        or 'недел' in text
        or 'дн' in text
    ):
        return 0

    if 'год' in text or 'года' in text or 'лет' in text:
        match = re.search(r'\d+', text)
        return (int(match.group()) if match else 1) * 12

    if 'месяц' in text:
        match = re.search(r'\d+', text)
        return int(match.group()) if match else 1

    return None


def _format_money(amounts: dict[str, Decimal]) -> str:
    if not amounts:
        return '0'
    return ', '.join(f'{_trim(amount)} {currency}' for currency, amount in amounts.items())


def _trim(value: Decimal) -> str:
    return format(value.normalize(), 'f')


def _clean_text(text: str) -> str:
    return re.sub(r'\s+', ' ', text).strip()


def _get(session: requests.Session, url: str, headers: dict[str, str]) -> str:
    response = session.get(url, headers=headers, timeout=30)
    _raise_for_status(response)
    return response.text


def _post(
    session: requests.Session,
    url: str,
    headers: dict[str, str],
    data: dict[str, str],
) -> str:
    response = session.post(url, headers=headers, data=data, timeout=30)
    _raise_for_status(response)
    return response.text


def _raise_for_status(response: requests.Response) -> None:
    try:
        response.raise_for_status()
    except requests.HTTPError as error:
        raise FunPayEarningsError(
            f'FunPay вернул HTTP {response.status_code}. '
            'Проверь ссылку, cookie и доступность страницы.',
        ) from error


def _raise_if_blocked(html: str) -> None:
    lowered = html.lower()
    if 'captcha' in lowered or 'cloudflare' in lowered:
        raise FunPayEarningsError('FunPay отдал капчу/антибот. Парсинг заблокирован.')
