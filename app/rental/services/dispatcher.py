from logging import getLogger

from app.config import get_settings
from app.database import get_session
from app.rental.common.commands import (
    CODE_COMMANDS,
    FAQ_COMMANDS,
    STOCK_COMMANDS,
    TIME_COMMANDS,
)
from app.rental.common.enums import ExtensionReasonEnum
from app.rental.funpay.events import NewMessageEvent, NewOrderEvent, NewReviewEvent
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.guard_code import GuardCodeService
from app.rental.services.info import InfoService
from app.rental.services.new_order import NewOrderService
from app.runtime import runtime


logger = getLogger(__name__)
settings = get_settings()

_processed_messages: set[int] = set()


async def on_new_order(event: NewOrderEvent) -> None:
    """Route a NEW_ORDER event to the rental core."""
    async with get_session() as session:
        await NewOrderService(session, runtime.get_deps()).handle(event)


async def on_new_message(event: NewMessageEvent) -> None:
    """Route a NEW_MESSAGE event to the matching command handler."""
    if event.message_id in _processed_messages:
        return
    _processed_messages.add(event.message_id)

    if event.author_id == 0:
        return  # игнорируем собственные сообщения

    text = event.text.strip().casefold()
    deps = runtime.get_deps()
    async with get_session() as session:
        if text in CODE_COMMANDS:
            await GuardCodeService(session, deps).handle(event)
        elif text in TIME_COMMANDS:
            await InfoService(session, deps).time_left(event.chat_id)
        elif text in STOCK_COMMANDS:
            await InfoService(session, deps).stock(event.chat_id)
        elif text in FAQ_COMMANDS:
            await InfoService(session, deps).faq(event.chat_id)


async def on_new_review(event: NewReviewEvent) -> None:
    """Route a NEW_REVIEW event to extend the rental."""
    async with get_session() as session:
        await ExtendRentalService(session, runtime.get_deps()).extend_by_order(
            event.order_id,
            settings.hours_for_review * 60,
            ExtensionReasonEnum.REVIEW,
        )
