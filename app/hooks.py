import logging
from logging import Handler
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

from pythonjsonlogger.jsonlogger import JsonFormatter

from app.config import get_settings


settings = get_settings()


def _build_formatter() -> logging.Formatter:
    """JSON-формат для прода или читаемый текст локально."""
    if settings.log_is_json:
        return JsonFormatter(
            '%(levelname)s %(asctime)s %(filename)s %(funcName)s '
            + '%(name)s %(message)s %(module)s %(lineno)d',
        )
    return logging.Formatter('%(asctime)s %(levelname)s %(name)s %(message)s')


def setup_logging() -> None:
    """Настроить логирование: stdout + (опционально) файл с суточной ротацией.

    Если задан settings.log_file, пишем ещё и в файл, который ротируется в
    полночь и хранит последние settings.log_retention_days дней (старое
    удаляется автоматически). stdout остаётся для journald/docker.
    """
    formatter = _build_formatter()
    handlers: list[Handler] = [logging.StreamHandler()]

    if settings.log_file:
        Path(settings.log_file).parent.mkdir(parents=True, exist_ok=True)
        file_handler = TimedRotatingFileHandler(
            settings.log_file,
            when='midnight',
            backupCount=settings.log_retention_days,
            encoding='utf-8',
            utc=True,
        )
        handlers.append(file_handler)

    for handler in handlers:
        handler.setFormatter(formatter)
    logging.basicConfig(level=settings.log_level, handlers=handlers)
