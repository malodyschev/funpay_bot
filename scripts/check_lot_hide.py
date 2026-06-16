"""Диагностика авто-скрытия лота на FunPay (через библиотечный get_lot_fields/save_lot).

ВНИМАНИЕ: реально меняет видимость лота (по умолчанию скрывает).

    python3 scripts/check_lot_hide.py <funpay_lot_id> [show]
"""

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.rental.funpay.real import build_account  # noqa: E402


def main() -> None:
    if len(sys.argv) < 2:
        sys.exit('usage: python3 scripts/check_lot_hide.py <funpay_lot_id> [show]')
    lot_id = int(sys.argv[1])
    target_active = len(sys.argv) > 2 and sys.argv[2] == 'show'

    settings = get_settings()
    print('авторизуюсь на FunPay...')
    account = build_account(
        settings.funpay_golden_key,
        settings.funpay_user_agent,
        settings.proxy_url or None,
    )
    print(f'ок, аккаунт {account.username} (id={account.id})')

    print(f'\nget_lot_fields({lot_id})...')
    try:
        fields = account.get_lot_fields(lot_id)
    except Exception as exc:  # noqa: BLE001
        print(f'❌ get_lot_fields: {type(exc).__name__}: {exc}')
        return
    print(f'✅ active={fields.active}, title_ru={fields.title_ru!r}, '
          f'deactivate_after_sale={fields.deactivate_after_sale}')

    print(f'\nsave_lot(active={target_active})...')
    try:
        fields.active = target_active
        account.save_lot(fields)
        print('✅ сохранено — проверь видимость лота на FunPay')
    except Exception as exc:  # noqa: BLE001
        print(f'❌ save_lot: {type(exc).__name__}: {exc}')


if __name__ == '__main__':
    main()
