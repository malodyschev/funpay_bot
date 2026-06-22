"""Сборка экранов админки, общих для нескольких хендлеров."""
from aiogram.types import InlineKeyboardMarkup

from app.rental.admin_bot import formatters as fmt, keyboards as kb
from app.rental.common.enums import ProviderEnum
from app.rental.models.lot import Lot
from app.rental.services.admin import AdminService


async def lot_screen(svc: AdminService, lot: Lot) -> tuple[str, InlineKeyboardMarkup]:
    """Экран лота — провайдер-aware: Chat-лот показывает Chat-аккаунты, Steam — Steam."""
    provider = await svc.lot_provider(lot)
    if provider == ProviderEnum.CHAT:
        accounts = await svc.chat_accounts_of_category(lot.category_id) if lot.category_id else []
        return fmt.fmt_lot_chat(lot, accounts), kb.chat_lot_accounts(lot, accounts)
    views = await svc.accounts_of_lot(lot.id)
    return fmt.fmt_lot(lot, len(views)), kb.lot_accounts(views, lot)
