"""Backup, restore and retention of the owner's data (design section 10).

The irreplaceable data is `aptscout.sqlite` and `photos/`. `backup` takes a
consistent copy of the database with SQLite's online backup (safe while the app
runs), mirrors new photos, and prunes old copies: the newest of each of the last
14 days, and the newest of each of the 6 months before that. The destination
(`APTSCOUT_BACKUP_DIR`) is the owner's choice; nothing is written without it.
"""

import os
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from . import config, db

DAILY = 14
MONTHLY = 6
PREFIX, SUFFIX = "aptscout-", ".sqlite"


def backup_dir() -> Path:
    value = os.environ.get("APTSCOUT_BACKUP_DIR")
    if not value:
        raise RuntimeError("APTSCOUT_BACKUP_DIR is not set; the owner chooses where backups go")
    return Path(value)


def stamp_of(path: Path) -> datetime | None:
    name = path.name
    if not (name.startswith(PREFIX) and name.endswith(SUFFIX)):
        return None
    try:
        return datetime.strptime(name[len(PREFIX):-len(SUFFIX)], "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def check(path: Path) -> None:
    """Raise if the file is not a healthy database."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    if result != "ok":
        raise RuntimeError(f"{path.name} failed the integrity check: {result}")


def to_keep(stamps: list[datetime], today: datetime) -> set[datetime]:
    """Newest copy of each of the last DAILY days, plus of each of the MONTHLY months before them."""
    keep: set[datetime] = set()
    horizon = today.date() - timedelta(days=DAILY - 1)
    days: dict = {}
    months: dict = {}
    for s in sorted(stamps):
        if s.date() >= horizon:
            days[s.date()] = s
        else:
            months[(s.year, s.month)] = s
    keep.update(days.values())
    keep.update(months[k] for k in sorted(months)[-MONTHLY:])
    return keep


def run(now: datetime | None = None) -> str:
    now = now or datetime.now()
    dest = backup_dir()
    dest.mkdir(parents=True, exist_ok=True)
    source = db.db_path()
    if not source.exists():
        raise RuntimeError("there is no database to back up yet")
    target = dest / f"{PREFIX}{now:%Y%m%d-%H%M%S}{SUFFIX}"
    src = sqlite3.connect(source)
    try:
        out = sqlite3.connect(target)
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    check(target)
    copied = _mirror_photos(dest / "photos")
    stamps = {stamp_of(p): p for p in dest.glob(f"{PREFIX}*{SUFFIX}") if stamp_of(p)}
    keep = to_keep(list(stamps), now)
    removed = 0
    for stamp, path in stamps.items():
        if stamp not in keep:
            path.unlink()
            removed += 1
    return f"backed up to {target.name}; {copied} new photos; pruned {removed} old copies"


def _mirror_photos(dest: Path) -> int:
    src = config.data_dir() / "photos"
    copied = 0
    if not src.is_dir():
        return 0
    for file in src.rglob("*"):
        if file.is_file():
            out = dest / file.relative_to(src)
            if not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, out)
                copied += 1
    return copied


def restore(name: str) -> str:
    """Put a backup in place. Stop the app first; the current database is kept aside."""
    dest = backup_dir()
    source = Path(name) if Path(name).is_absolute() or Path(name).exists() else dest / name
    if not source.exists():
        raise RuntimeError(f"no such backup: {name}")
    check(source)
    live = db.db_path()
    live.parent.mkdir(parents=True, exist_ok=True)
    if live.exists():
        aside = live.with_name(live.name + f".before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        shutil.move(live, aside)
    for extra in (live.with_name(live.name + "-wal"), live.with_name(live.name + "-shm")):
        extra.unlink(missing_ok=True)
    shutil.copy2(source, live)
    photos = dest / "photos"
    restored = 0
    if photos.is_dir():
        for file in photos.rglob("*"):
            out = config.data_dir() / "photos" / file.relative_to(photos)
            if file.is_file() and not out.exists():
                out.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(file, out)
                restored += 1
    check(live)
    return f"restored {source.name}; {restored} photos copied back"
