import hashlib
import os
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from argon2 import PasswordHasher

passwords = PasswordHasher()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def now() -> str:
    return datetime.now(UTC).isoformat(timespec='milliseconds')


@contextmanager
def connect(path):
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys = ON')
    try:
        with db:
            yield db
    finally:
        db.close()


def initialize(path):
    with connect(path) as db:
        db.executescript(Path(__file__).with_name('schema.sql').read_text())
        db.execute('PRAGMA user_version = 1')


def database_path():
    return os.environ.get('OMNI_DB', 'omnic360.sqlite3')
