import os
import pathlib
import tempfile

from cryptography.fernet import Fernet


_db_path = pathlib.Path(tempfile.gettempdir()) / 'funpay_bot_test.db'
if _db_path.exists():
    _db_path.unlink()

os.environ['ENV_FILE'] = '/dev/null'
os.environ['DB_URL'] = f'sqlite+aiosqlite:///{_db_path}'
os.environ['ENCRYPTION_KEY'] = Fernet.generate_key().decode()
os.environ['WARN_BEFORE_MINUTES'] = '10'
os.environ['HOURS_FOR_REVIEW'] = '1'
os.environ['PASSWORD_CHANGE_RETRIES'] = '3'
