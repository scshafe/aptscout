"""The host's scheduled work, as one long-running process (design section 14).

Nightly: backup. Weekly: CTA feed check; a new feed is imported with its stops.
Monthly: OSM extract, Park District pools, places. After a new feed the owner's
stack rebuilds the OTP graph (`build-otp-inputs`, then the OTP container) and
`recompute` warms the travel times; those need the stack, so they are not run here.
Last run times persist in `cache/jobs.json`.
"""

import json
import sys
import time
import traceback
from datetime import datetime, timedelta

from . import backup, config, datasets

INTERVALS = {"backup": timedelta(days=1), "gtfs": timedelta(days=7), "osm": timedelta(days=30)}


def _path():
    return config.cache_dir() / "jobs.json"


def last_runs() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def mark(name: str, when: datetime) -> None:
    runs = last_runs()
    runs[name] = when.isoformat(timespec="seconds")
    _path().parent.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(runs, indent=2), encoding="utf-8")


def due(runs: dict, now: datetime) -> list[str]:
    """Jobs whose interval has passed (or that never ran), most frequent first."""
    out = []
    for name, interval in INTERVALS.items():
        last = runs.get(name)
        if last is None or now - datetime.fromisoformat(last) >= interval:
            out.append(name)
    return out


def run_job(name: str, city: dict) -> str:
    if name == "backup":
        return backup.run()
    if name == "gtfs":
        message = datasets.fetch_gtfs(city)
        if "imported" in message:
            datasets.import_places(city)
        return message
    if name == "osm":
        return "; ".join([datasets.fetch_osm(city), datasets.fetch_pools(city), datasets.import_places(city)])
    raise ValueError(name)


def loop(poll_seconds: int = 900) -> None:
    city = config.load_city()
    while True:
        now = datetime.now()
        for name in due(last_runs(), now):
            try:
                print(f"{now:%F %T} {name}: {run_job(name, city)}", flush=True)
                mark(name, datetime.now())
            except Exception:  # a failed job is retried at the next poll, and must not stop the others
                print(f"{now:%F %T} {name} failed:\n{traceback.format_exc()}", file=sys.stderr, flush=True)
        time.sleep(poll_seconds)
