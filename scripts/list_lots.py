"""Показать реальные текущие офферы аккаунта на FunPay (их id и названия).

    python3 scripts/list_lots.py
"""

import os
import sys


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings  # noqa: E402
from app.rental.funpay.real import build_account  # noqa: E402


def main() -> None:
    settings = get_settings()
    print('авторизуюсь на FunPay...')
    account = build_account(
        settings.funpay_golden_key,
        settings.funpay_user_agent,
        settings.proxy_url or None,
    )
    print(f'ок, аккаунт {account.username} (id={account.id})')

    profile = account.get_user(account.id)
    lots = profile.get_lots()
    print(f'\n[A] публичный профиль (только активные): {len(lots)}')
    subcategory_ids = set()
    for lot in lots:
        title = getattr(lot, 'title', None) or getattr(lot, 'description', None) or ''
        sub = getattr(lot, 'subcategory', None)
        sub_id = getattr(sub, 'id', None)
        subcategory_ids.add(sub_id)
        print(f'  id={lot.id}  [sub={sub_id}]  {str(title)[:60]!r}')

    print('\n[B] управление лотами (активные + НЕактивные), get_my_subcategory_lots:')
    if not subcategory_ids:
        print('    (нет активных лотов → не знаю подкатегорию; запусти когда лот активен,')
        print('     или скажи id подкатегории — добавлю аргументом)')
    for sub_id in subcategory_ids:
        if sub_id is None:
            continue
        try:
            my = account.get_my_subcategory_lots(sub_id)
        except Exception as exc:  # noqa: BLE001
            print(f'    sub={sub_id}: ОШИБКА {type(exc).__name__}: {exc}')
            continue
        print(f'    sub={sub_id}: {len(my)} офферов')
        for offer in my:
            print(f'      id={offer.id}  active={offer.active}  {str(offer.description)[:55]!r}')


if __name__ == '__main__':
    main()
