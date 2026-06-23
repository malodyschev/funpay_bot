from logging import getLogger

from app.config import get_settings
from app.database import get_session
from app.rental.common.commands import (
    ACC_COMMANDS,
    ADMIN_COMMANDS,
    CHAT_ACC_COMMANDS,
    CHAT_CODE_COMMANDS,
    CHAT_REFUND_COMMANDS,
    CHAT_TIME_COMMANDS,
    CODE_COMMANDS,
    EXTEND_COMMANDS,
    FAQ_COMMANDS,
    REFUND_COMMANDS,
    STOCK_ALL_COMMANDS,
    STOCK_COMMANDS,
    TIME_COMMANDS,
)
from app.rental.common.enums import ExtensionReasonEnum
from app.rental.funpay.events import NewMessageEvent, NewOrderEvent, NewReviewEvent
from app.rental.repositories.rental import RentalRepository
from app.rental.services.chat_rental import ChatRentalService
from app.rental.services.extend_rental import ExtendRentalService
from app.rental.services.guard_code import GuardCodeService
from app.rental.services.info import InfoService
from app.rental.services.new_order import NewOrderService
from app.runtime import runtime


_CHAT_CODE_MESSAGES = {
    'expired': (
        '⏳ Ваша подписка закончилась 😔\n'
        'Спасибо, что были с нами! Чтобы снова пользоваться — '
        'оформите новый заказ, и мы всё сразу подключим. 🙌'
    ),
    'none': (
        '🔑 Код входа выдаётся во время активной аренды.\n'
        'Сначала оплатите заказ — и сразу пришлём код по команде !chat-code. 😊'
    ),
    'no_2fa': '⚠️ Код сейчас недоступен. Напишите !admin — мы быстро поможем. 🙌',
}


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
        elif text in CHAT_CODE_COMMANDS:
            result = await ChatRentalService(session, deps).code_for_chat(event.chat_id)
            message = (
                f'🔑 Ваш код входа: {result.code}\n'
                '⏳ Действует ~30 секунд — введите быстро. Нужен новый — снова !chat-code.'
                if result.reason == 'ok'
                else _CHAT_CODE_MESSAGES[result.reason]
            )
            await deps.funpay.send_message(event.chat_id, message)
        elif text in CHAT_ACC_COMMANDS:
            if not await ChatRentalService(session, deps).send_credentials(event.chat_id):
                await _no_chat_rental(deps, event.chat_id)
        elif text in CHAT_TIME_COMMANDS:
            if not await ChatRentalService(session, deps).send_time_left(event.chat_id):
                await _no_chat_rental(deps, event.chat_id)
        elif text in CHAT_REFUND_COMMANDS:
            if not await ChatRentalService(session, deps).request_refund(event.chat_id):
                await _no_chat_rental(deps, event.chat_id)
        elif text in ACC_COMMANDS:
            # Chat-аренда имеет приоритет; иначе — Steam.
            if not await ChatRentalService(session, deps).send_credentials(event.chat_id):
                await InfoService(session, deps).send_credentials(event.chat_id)
        elif text in ADMIN_COMMANDS:
            await InfoService(session, deps).call_admin(event.chat_id)
        elif text in REFUND_COMMANDS:
            if not await ChatRentalService(session, deps).request_refund(event.chat_id):
                await InfoService(session, deps).request_refund(event.chat_id)
        elif text in EXTEND_COMMANDS:
            await InfoService(session, deps).extend_info(event.chat_id)
        elif text in STOCK_ALL_COMMANDS:
            await InfoService(session, deps).stock_all(event.chat_id)
        elif text in STOCK_COMMANDS:
            await InfoService(session, deps).stock(event.chat_id)
        elif text in TIME_COMMANDS:
            if not await ChatRentalService(session, deps).send_time_left(event.chat_id):
                await InfoService(session, deps).time_left(event.chat_id)
        elif text in FAQ_COMMANDS:
            await InfoService(session, deps).faq(event.chat_id)


async def _no_chat_rental(deps, chat_id: int) -> None:
    await deps.funpay.send_message(
        chat_id,
        '🤔 Активной подписки на этом чате не вижу. '
        'Если только что оплатили — напишите !admin.',
    )


async def on_new_review(event: NewReviewEvent) -> None:
    """Route a NEW_REVIEW event to extend the rental."""
    async with get_session() as session:
        await ExtendRentalService(session, runtime.get_deps()).extend_by_order(
            event.order_id,
            settings.hours_for_review * 60,
            ExtensionReasonEnum.REVIEW,
        )


async def on_new_review_by_chat(chat_id: int) -> None:
    """Отзыв пришёл системным сообщением в чат — продлеваем аренду этого чата."""
    deps = runtime.get_deps()
    async with get_session() as session:
        rental = await RentalRepository(session).get_active_by_chat(chat_id)
        if rental:  # Steam-аренда
            await ExtendRentalService(session, deps).extend_by_id(
                rental.id,
                settings.hours_for_review * 60,
                ExtensionReasonEnum.REVIEW,
            )
            return
        # Иначе — возможно, это Chat-аренда (+1 день за отзыв).
        await ChatRentalService(session, deps).extend_for_review(chat_id)
