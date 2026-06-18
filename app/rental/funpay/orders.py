from dataclasses import dataclass
from logging import getLogger


logger = getLogger(__name__)


@dataclass
class UnconfirmedOrder:
    """Заказ, который покупатель оплатил, но не подтвердил выполнение (state=paid)."""

    id: str
    buyer: str
    description: str


def fetch_unconfirmed(account, max_pages: int = 20) -> list[UnconfirmedOrder]:
    """Все неподтверждённые заказы продавца (оплачены, ждут подтверждения).

    Используем get_sales(state='paid') — FunPay сам отдаёт только PAID-заказы,
    листаем страницы через start_from (курсор). Это надёжнее ручного парсинга
    HTML и пагинации.
    """
    result: list[UnconfirmedOrder] = []
    seen: set[str] = set()
    start_from: str | None = None
    for _ in range(max_pages):
        next_id, batch, *_ = account.get_sales(start_from=start_from, state='paid')
        added = False
        for order in batch:
            if order.id in seen:
                continue
            seen.add(order.id)
            result.append(UnconfirmedOrder(
                id=str(order.id),
                buyer=order.buyer_username or '',
                description=order.description or '',
            ))
            added = True
        if not next_id or not added:
            break
        start_from = next_id
    return result
