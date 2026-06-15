from dataclasses import dataclass


@dataclass
class NewOrderEvent:
    """Новый оплаченный заказ на FunPay."""

    order_id: str
    lot_title: str
    buyer_id: int
    buyer_username: str
    chat_id: int


@dataclass
class NewMessageEvent:
    """Новое сообщение в чате FunPay."""

    chat_id: int
    message_id: int
    author_id: int
    text: str


@dataclass
class NewReviewEvent:
    """Новый отзыв по заказу."""

    order_id: str
    rating: int | None = None
    text: str | None = None
