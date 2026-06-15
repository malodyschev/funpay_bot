from logging import getLogger

from aiogram import Router
from aiogram.types import CallbackQuery

from app.database import get_session
from app.rental.admin_bot.callbacks import Refund
from app.rental.services.refund import RefundService
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()


@router.callback_query(Refund.filter())
async def handle_refund(cb: CallbackQuery, callback_data: Refund) -> None:
    if not callback_data.yes:
        await cb.message.edit_text('↩️ Возврат отклонён.')
        await cb.answer()
        return

    await cb.answer('Оформляю возврат…')
    async with get_session() as session:
        await RefundService(session, runtime.get_deps()).execute(callback_data.order_id)
    await cb.message.edit_text(f'✅ Возврат по заказу {callback_data.order_id} выполнен.')
