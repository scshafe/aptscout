"""SQLite access and numbered migrations (docs/design.md section 10)."""

import re
import sqlite3
from pathlib import Path

from . import config

MIGRATIONS = Path(__file__).parent / "migrations"


def db_path() -> Path:
    return config.data_dir() / "aptscout.sqlite"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    migrate(conn)
    return conn


def migrate(conn: sqlite3.Connection) -> None:
    """Apply each NNN_name.sql once, in order, and record it."""
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migration (name TEXT PRIMARY KEY)")
    done = {row[0] for row in conn.execute("SELECT name FROM schema_migration")}
    for sql in sorted(MIGRATIONS.glob("[0-9][0-9][0-9]_*.sql")):
        if sql.name in done:
            continue
        # executescript commits first, so each migration is its own unit
        conn.executescript(sql.read_text(encoding="utf-8"))
        conn.execute("INSERT INTO schema_migration (name) VALUES (?)", (sql.name,))
        conn.commit()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "category"
