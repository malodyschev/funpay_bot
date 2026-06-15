from collections import defaultdict


def render_delivery(
    template: str,
    *,
    login: str,
    password: str,
    minutes: int,
    game: str = '',
) -> str:
    """Render a delivery message, tolerating unknown placeholders.

    Поддерживаемые плейсхолдеры: {login}, {password}, {minutes}, {game}.
    Незнакомые плейсхолдеры заменяются пустой строкой, чтобы кривой
    шаблон не ронял выдачу.
    """
    values: dict[str, object] = defaultdict(str)
    values.update(login=login, password=password, minutes=minutes, game=game)
    return template.format_map(values)
