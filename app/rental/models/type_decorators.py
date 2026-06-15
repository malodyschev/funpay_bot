from enum import Enum
from typing import Any

from sqlalchemy import String, TypeDecorator
from sqlalchemy.engine.interfaces import Dialect


class EnumAsString(TypeDecorator):
    """Enum хранится своим строковым value — статус читается прямо в БД."""

    impl = String(32)
    cache_ok = True

    def __init__(self, type_enum: type[Enum]) -> None:
        """Init."""
        self.type_enum = type_enum
        super().__init__()

    def process_bind_param(self, value: Any | None, dialect: Dialect) -> str | None:
        """Enum → строка для БД."""
        if value is None:
            return value
        return value.value

    def process_result_value(self, value: Any | None, dialect: Dialect) -> Enum | None:
        """Строка из БД → Enum."""
        if value is None:
            return value
        return self.type_enum(value)
