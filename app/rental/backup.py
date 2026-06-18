import asyncio
import contextlib
import gzip
import os
from datetime import datetime, timedelta
from logging import getLogger

from aiogram import Bot
from aiogram.types import BufferedInputFile

from app.config import get_settings


logger = getLogger(__name__)

BACKUP_HOUR = 4  # 04:00 по локальному времени контейнера (TZ=Europe/Moscow)


async def _pg_dump_gz() -> bytes:
    """Снять дамп БД через pg_dump и сжать gzip. Бросает при ошибке pg_dump."""
    s = get_settings()
    env = {**os.environ, 'PGPASSWORD': s.db_password}
    proc = await asyncio.create_subprocess_exec(
        'pg_dump', '-h', s.db_host, '-p', str(s.db_port), '-U', s.db_username, s.db_name,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    out, err = await proc.communicate()
    if proc.returncode != 0:
        raise RuntimeError(f'pg_dump rc={proc.returncode}: {err.decode(errors="replace")[:300]}')
    return gzip.compress(out)


async def make_and_send_backup(bot: Bot, chat_ids: list[int]) -> str:
    """Сделать дамп БД и отправить .sql.gz в указанные чаты. Возвращает имя файла."""
    data = await _pg_dump_gz()
    fname = f'funpay_{datetime.now():%Y-%m-%d_%H%M}.sql.gz'
    caption = (
        f'🗄 Бэкап БД {fname} ({len(data) / 1024:.0f} КБ)\n'
        '⚠️ encryption_key сюда НЕ присылай — храни отдельно, иначе дамп можно расшифровать.'
    )
    for chat_id in chat_ids:
        with contextlib.suppress(Exception):
            await bot.send_document(
                chat_id, BufferedInputFile(data, filename=fname), caption=caption,
            )
    return fname


def _seconds_until_hour(hour: int) -> float:
    """Сколько секунд до ближайшего HH:00 (по локальному времени)."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def run_backup_scheduler(bot: Bot, admin_ids: list[int]) -> None:
    """Раз в сутки в BACKUP_HOUR:00 слать бэкап БД админам в Telegram."""
    logger.info('backup scheduler started (ежедневно в %02d:00)', BACKUP_HOUR)
    while True:
        await asyncio.sleep(_seconds_until_hour(BACKUP_HOUR))
        try:
            fname = await make_and_send_backup(bot, admin_ids)
            logger.info('daily backup sent: %s', fname)
        except Exception:
            logger.exception('scheduled backup failed')
