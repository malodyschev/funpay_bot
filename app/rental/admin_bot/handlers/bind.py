import contextlib
import html
from logging import getLogger

from aiogram import Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.config import get_settings
from app.database import get_session
from app.rental.admin_bot import keyboards as kb
from app.rental.admin_bot.callbacks import BindAccount
from app.rental.common.exceptions import DuplicateException, SteamModuleError
from app.rental.services.account_loader import AccountLoaderService
from app.rental.services.admin import AdminService
from app.rental.steam.add_authenticator import (
    CODE_TYPE_DEVICE,
    CODE_TYPE_EMAIL,
    add_authenticator,
    begin_credentials_login,
    finalize_authenticator,
    poll_for_token,
    submit_code_and_get_token,
)
from app.runtime import runtime


logger = getLogger(__name__)
router = Router()
settings = get_settings()


class BindForm(StatesGroup):
    login = State()
    password = State()
    login_code = State()
    activation_code = State()


def _proxy() -> str | None:
    return settings.proxy_url or None


@router.callback_query(BindAccount.filter())
async def bind_start(cb: CallbackQuery, callback_data: BindAccount, state: FSMContext) -> None:
    await state.set_state(BindForm.login)
    await state.update_data(lot_id=callback_data.lot_id)
    await cb.message.answer(
        '🔑 <b>Привязка нового аккаунта.</b>\n'
        'Бот сам создаст аутентификатор. Пришли <b>логин</b> Steam:',
    )
    await cb.answer()


@router.message(BindForm.login)
async def bind_login(message: Message, state: FSMContext) -> None:
    await state.update_data(login=(message.text or '').strip())
    await state.set_state(BindForm.password)
    await message.answer('Теперь пришли <b>пароль</b> Steam:')


@router.message(BindForm.password)
async def bind_password(message: Message, state: FSMContext) -> None:
    password = message.text or ''
    await state.update_data(password=password)
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()  # пароль не оставляем в чате

    data = await state.get_data()
    try:
        begin = await begin_credentials_login(data['login'], password, proxy=_proxy())
    except SteamModuleError as exc:
        await state.clear()
        await message.answer(f'❌ {exc}')
        return

    types = begin['confirmation_types']
    await state.update_data(
        client_id=str(begin['client_id']),
        request_id=str(begin['request_id']),
        steamid=str(begin['steamid']),
    )

    if CODE_TYPE_DEVICE in types:
        await state.clear()
        await message.answer('❌ У аккаунта уже есть мобильный аутентификатор.')
        return

    if CODE_TYPE_EMAIL in types:
        await state.set_state(BindForm.login_code)
        await message.answer('✉️ Steam отправил код на почту. Пришли <b>код входа</b>:')
        return

    # Steam Guard нет (типы=[1]/пусто) — вход без кода, сразу создаём аутентификатор.
    await message.answer('У аккаунта нет Steam Guard — захожу без кода, создаю аутентификатор…')
    try:
        access_token = await poll_for_token(
            client_id=str(begin['client_id']),
            request_id=str(begin['request_id']),
            proxy=_proxy(),
        )
    except SteamModuleError as exc:
        await state.clear()
        await message.answer(f'❌ {exc}')
        return
    await _request_authenticator(message, state, access_token)


@router.message(BindForm.login_code)
async def bind_login_code(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    try:
        access_token = await submit_code_and_get_token(
            client_id=data['client_id'],
            request_id=data['request_id'],
            steamid=data['steamid'],
            code=(message.text or '').strip(),
            code_type=CODE_TYPE_EMAIL,
            proxy=_proxy(),
        )
    except SteamModuleError as exc:
        await state.clear()
        await message.answer(f'❌ {exc}')
        return
    await _request_authenticator(message, state, access_token)


async def _request_authenticator(message: Message, state: FSMContext, access_token: str) -> None:
    """Создать аутентификатор, отдать админу код восстановления, ждать код активации."""
    data = await state.get_data()
    try:
        secrets = await add_authenticator(
            access_token=access_token,
            steamid=data['steamid'],
            proxy=_proxy(),
        )
    except SteamModuleError as exc:
        await state.clear()
        await message.answer(f'❌ {exc}')
        return

    revocation = secrets.get('revocation_code', '')
    await state.update_data(
        access_token=access_token,
        shared_secret=secrets['shared_secret'],
        identity_secret=secrets['identity_secret'],
        revocation_code=revocation,
        device_id=secrets['device_identifier'],
    )
    # Код восстановления — сразу админу (на случай сбоя финализации).
    await message.answer(
        f'⚠️ <b>Сохрани код восстановления!</b>\n'
        f'Аккаунт: <code>{html.escape(data["login"])}</code>\n'
        f'Revocation code: <code>{html.escape(revocation)}</code>\n'
        f'Без него нельзя снять аутентификатор.',
    )
    await state.set_state(BindForm.activation_code)
    await message.answer('📱 Steam отправил код активации (SMS или почта). Пришли его:')


@router.message(BindForm.activation_code)
async def bind_activation_code(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    with contextlib.suppress(TelegramBadRequest):
        await message.delete()
    try:
        await finalize_authenticator(
            access_token=data['access_token'],
            steamid=data['steamid'],
            shared_secret=data['shared_secret'],
            activation_code=(message.text or '').strip(),
            proxy=_proxy(),
        )
    except SteamModuleError as exc:
        await state.clear()
        await message.answer(
            f'❌ {exc}\nКод восстановления уже отправлен выше — сохрани его.',
        )
        return

    lot_id = data['lot_id']
    try:
        async with get_session() as session:
            account = await AccountLoaderService(session).create_account(
                lot_id=lot_id,
                login=data['login'],
                password=data['password'],
                steam_id=data['steamid'],
                shared_secret=data['shared_secret'],
                identity_secret=data['identity_secret'],
                revocation_code=data['revocation_code'],
                device_id=data['device_id'],
            )
            views = await AdminService(session, runtime.get_deps()).accounts_of_lot(lot_id)
    except DuplicateException as exc:
        await state.clear()
        await message.answer(f'⚠️ Аутентификатор привязан, но в пул не добавлен: {exc}')
        return

    await state.clear()
    await message.answer(
        f'✅ Аккаунт #{account.id} ({account.login}) привязан и добавлен в лот.',
        reply_markup=kb.lot_accounts(views, lot_id),
    )
