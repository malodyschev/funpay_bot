"""Журнал входов арендатора (= запросов кода) в рамках одной аренды.

Храним ВСЕ моменты запроса кода в одном текстовом поле `code_log` строки аренды:
ISO-таймстампы через перевод строки (по одному на запрос). Источник для «когда
заходил» при кике по истечении и в карточке аренды в админке. Журнал живёт на
строке аренды → у новой аренды он пустой (прошлые входы не учитываются).
"""
from datetime import datetime


_SEP = '\n'


def append_code_time(log: str | None, when: datetime) -> str:
    """Добавить ещё один момент входа к журналу (вернуть новое значение поля)."""
    entry = when.replace(microsecond=0).isoformat()
    return f'{log}{_SEP}{entry}' if log else entry


def parse_code_times(log: str | None) -> list[datetime]:
    """Разобрать журнал в список моментов входа (в порядке от первого к последнему)."""
    if not log:
        return []
    times: list[datetime] = []
    for line in log.split(_SEP):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            times.append(datetime.fromisoformat(stripped))
        except ValueError:
            continue
    return times
