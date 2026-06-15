import logging

from pythonjsonlogger.jsonlogger import JsonFormatter

from app.config import get_settings


settings = get_settings()


def setup_logging() -> None:
    """Настроить логирование: JSON-формат для прода или читаемый текст локально."""
    handler = logging.StreamHandler()
    if settings.log_is_json:
        handler.setFormatter(
            JsonFormatter(
                '%(levelname)s %(asctime)s %(filename)s %(funcName)s '
                + '%(name)s %(message)s %(module)s %(lineno)d',
            ),
        )
    else:
        handler.setFormatter(
            logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s'),
        )
    logging.basicConfig(level=settings.log_level, handlers=[handler])
