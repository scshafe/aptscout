"""Paths and the city configuration (docs/design.md section 11)."""

import json
import os
from pathlib import Path

CITIES_DIR = Path(__file__).parent / "cities"


def data_dir() -> Path:
    """The runtime data directory: the owner's database and rebuildable caches.

    Outside version control on the host (design section 10); `state/` in the
    checkout is gitignored for development.
    """
    return Path(os.environ.get("APTSCOUT_DATA_DIR", "state")).resolve()


def cache_dir() -> Path:
    return data_dir() / "cache"


def load_city(name: str | None = None) -> dict:
    name = name or os.environ.get("APTSCOUT_CITY", "chicago")
    with open(CITIES_DIR / f"{name}.json", encoding="utf-8") as handle:
        return json.load(handle)
