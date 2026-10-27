"""The shipped categories and how OSM tags map to them (design section 3.2)."""

import sqlite3

# key, name, colour, OSM tag matches (any one matches), visible by default
BUILTIN = [
    ("grocery", "Grocery", "#2e9d4d", [("shop", "supermarket"), ("shop", "greengrocer")], 1),
    ("convenience", "Convenience store", "#8cc084", [("shop", "convenience")], 0),
    ("gym", "Gym", "#d9531e", [("leisure", "fitness_centre")], 1),
    ("lap_pool", "Lap pool", "#1f78d1", [], 1),
    ("park", "Park", "#4f8a3c", [("leisure", "park")], 1),
    ("pharmacy", "Pharmacy", "#c2185b", [("amenity", "pharmacy")], 1),
    ("cafe", "Cafe", "#8d6e63", [("amenity", "cafe")], 0),
    ("library", "Library", "#6a4fb3", [("amenity", "library")], 1),
    ("laundromat", "Laundromat", "#00897b", [("shop", "laundry")], 0),
    ("rail_station", "CTA rail station", "#222222", [], 1),
    ("bus_stop", "CTA bus stop", "#777777", [], 0),
]
BUILTIN_NAMES = {key: name for key, name, *_ in BUILTIN}
# Categories whose places come from the CTA feed, not OSM (design 3.4).
TRANSIT = {"rail_station", "bus_stop"}
LAP_POOL_STATES = ("unreviewed", "confirmed", "rejected")


def classify(tags: dict) -> str | None:
    """The category key for an OSM object's tags, or None.

    Lap pools are decided by `lap_likelihood`; a sports centre counts as a gym
    when it lists fitness, and as a pool candidate when it lists swimming.
    """
    leisure = tags.get("leisure")
    sports = set((tags.get("sport") or "").split(";"))
    if leisure == "swimming_pool" or (leisure in ("sports_centre", "fitness_centre") and "swimming" in sports):
        return "lap_pool"
    if leisure == "sports_centre" and "fitness" in sports:
        return "gym"
    for key, _name, _colour, matches, _visible in BUILTIN:
        if any(tags.get(k) == v for k, v in matches):
            if key == "park" and not tags.get("name"):
                continue  # unnamed green patches are noise
            return key
    return None


_RESIDENT_WORDS = ("apartment", "condo", "residence", "residential", "tower", "hotel", "hilton", "marriott")


def _metres(value: str | None) -> float | None:
    """Parse an OSM length such as '25', '25 m' or '75 ft' to metres."""
    if not value:
        return None
    try:
        parts = value.replace(",", ".").split()
        number = float(parts[0])
    except (ValueError, IndexError):
        return None
    if len(parts) > 1 and parts[1].lower() in ("ft", "feet", "'"):
        return number * 0.3048
    return number


def lap_likelihood(tags: dict) -> str:
    """'likely', 'maybe' or 'unlikely' for a swimming pool candidate (design 3.3).

    Not decided from tags alone: the owner confirms or rejects every candidate.
    """
    name = (tags.get("name") or "").lower()
    if tags.get("access") in ("private", "residents", "no"):
        return "unlikely"
    if tags.get("swimming_pool") in ("hot_tub", "spa", "wading", "kiddie") or tags.get("sauna"):
        return "unlikely"
    if any(w in name for w in _RESIDENT_WORDS) or tags.get("tourism") in ("hotel", "motel"):
        return "unlikely"
    length = _metres(tags.get("length"))
    if (length and length >= 20) or tags.get("lanes"):
        return "likely"
    if "swimming" in (tags.get("sport") or "").split(";") and tags.get("access") in (None, "yes", "public", "customers", "permissive"):
        return "likely" if tags.get("location") == "indoor" or tags.get("leisure") != "swimming_pool" else "maybe"
    if not name and not tags.get("operator"):
        return "unlikely"  # an unnamed pool with no cue is usually a residential amenity
    return "maybe"


def seed_user_categories(conn: sqlite3.Connection, owner_id: int) -> None:
    """Give a new owner the shipped categories (idempotent)."""
    for key, name, colour, _matches, visible in BUILTIN:
        conn.execute(
            "INSERT OR IGNORE INTO category (owner_id, key, name, colour, builtin, visible) VALUES (?,?,?,?,1,?)",
            (owner_id, key, name, colour, visible),
        )
    conn.commit()
