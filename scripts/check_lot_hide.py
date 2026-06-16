"""Диагностика авто-скрытия лота на FunPay.

Показывает, что реально отвечает FunPay на offerEdit и срабатывает ли
скрытие/показ. ВНИМАНИЕ: реально меняет видимость лота (по умолчанию скрывает).

    python3 scripts/check_lot_hide.py <funpay_lot_id> [show]

<funpay_lot_id> — id оффера FunPay (поле funpay_lot_id в нашей таблице lots,
видно в карточке лота админки). 'show' в конце — наоборот показать лот.
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

    import FunPayAPI
    print(f'FunPayAPI version: {getattr(FunPayAPI, "__version__", "?")}')

    variants = {
        'lib (json ct + xrw)': {
            'accept': '*/*', 'content-type': 'application/json',
            'x-requested-with': 'XMLHttpRequest',
        },
        'xrw only + accept json': {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'x-requested-with': 'XMLHttpRequest',
        },
        'xrw + referer': {
            'accept': 'application/json, text/javascript, */*; q=0.01',
            'x-requested-with': 'XMLHttpRequest',
            'referer': f'https://funpay.com/lots/offerEdit?offer={lot_id}',
        },
        'no headers': {},
    }
    for name, headers in variants.items():
        resp = account.method('get', f'lots/offerEdit?offer={lot_id}', headers, {})
        ct = resp.headers.get('content-type')
        try:
            j = resp.json()
            verdict = f'JSON OK, keys={list(j.keys())[:6]}'
        except Exception:
            verdict = f'НЕ JSON (len={len(resp.text)})'
        print(f'\n[{name}] status={resp.status_code} ct={ct}\n    {verdict}')

    print('\n[2] все поля на полной странице (вне зависимости от <form>)')
    from bs4 import BeautifulSoup
    from FunPayAPI import types

    page = account.method('get', f'lots/offerEdit?offer={lot_id}', {}, {}, raise_not_200=True)
    soup = BeautifulSoup(page.text, 'html.parser')
    all_named = [
        el.get('name')
        for el in soup.find_all(['input', 'select', 'textarea'])
        if el.get('name')
    ]
    print(f'    всего именованных полей: {len(all_named)}')
    print(f'    имена: {all_named[:40]}')
    offer_like = [n for n in all_named if 'fields[' in n or n in ('csrf_token', 'offer_id', 'node_id', 'price', 'amount', 'active', 'deactivate_after_sale')]
    print(f'    похожие на поля оффера: {offer_like}')

    if not any('fields[' in n or n in ('offer_id', 'csrf_token') for n in all_named):
        print('    ❌ полей оффера на странице нет (редактор рендерится через JS).')
        return

    print('\n[3] собираю LotFields из всех полей страницы и сохраняю')
    result = {'active': '', 'deactivate_after_sale': ''}
    for field in soup.find_all('input'):
        name = field.get('name')
        if name and name not in ('active', 'deactivate_after_sale', 'query'):
            result[name] = field.get('value') or ''
    for field in soup.find_all('textarea'):
        if field.get('name'):
            result[field['name']] = field.text or ''
    for field in soup.find_all('select'):
        if field.get('name'):
            opt = field.find('option', selected=True)
            result[field['name']] = opt['value'] if opt else ''
    for field in soup.find_all('input', {'type': 'checkbox'}, checked=True):
        if field.get('name'):
            result[field['name']] = 'on'
    print(f'    собрано полей: {len(result)}, ключи: {sorted(result)}')
    try:
        fields = types.LotFields(lot_id, result)
        fields.active = target_active
        account.save_lot(fields)
        print(f'    save_lot(active={target_active}) выполнен ✅ — проверь лот на FunPay')
    except Exception as exc:  # noqa: BLE001
        print(f'    ОШИБКА save_lot: {type(exc).__name__}: {exc}')


if __name__ == '__main__':
    main()
