"""Warm the travel time cache after a data change and drop what is stale (design 4.4).

Run after `fetch-gtfs` / an OTP graph rebuild. Until then the app computes
times lazily when asked, so the first view of a changed apartment is slow.
"""

from . import db, otp, routing, weekly


def run() -> str:
    conn = db.connect()
    router, engine = routing.make_router(), otp.make_engine()
    version = weekly.data_version(router, engine)
    done = 0
    for apt in conn.execute("SELECT * FROM apartment WHERE lat IS NOT NULL").fetchall():
        weekly.weekly_for_apartment(conn, apt["owner_id"], apt, router, engine)
        done += 1
    with conn:
        stale = conn.execute("DELETE FROM travel_time WHERE version != ?", (version,)).rowcount
    return f"recomputed {done} apartments; dropped {stale} stale times (version {version})"
