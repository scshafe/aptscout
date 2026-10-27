-- M4: destinations (what the owner travels to, how often, how), the cached
-- travel times and the owner's settings (design sections 4.4, 5, 6.2).
CREATE TABLE destination (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES app_user(id),
    name TEXT NOT NULL,
    kind TEXT NOT NULL,                 -- place | category
    address TEXT NOT NULL DEFAULT '',
    lat REAL,
    lon REAL,
    category_key TEXT,
    selection_rule TEXT NOT NULL DEFAULT 'best',
    n INTEGER NOT NULL DEFAULT 3,
    trips_per_week REAL NOT NULL DEFAULT 1,
    mode TEXT NOT NULL DEFAULT 'walk',
    time_band TEXT NOT NULL DEFAULT 'weekday_midday',
    return_band TEXT,
    max_minutes INTEGER
);
CREATE INDEX destination_owner ON destination (owner_id);

-- One way, one band. `version` ties the number to the data it came from
-- (router and CTA feed), so a new feed makes it stale and it is recomputed.
CREATE TABLE travel_time (
    apartment_id INTEGER NOT NULL REFERENCES apartment(id) ON DELETE CASCADE,
    destination_id INTEGER NOT NULL REFERENCES destination(id) ON DELETE CASCADE,
    place_id INTEGER NOT NULL,          -- 0 for a destination that is a point
    direction TEXT NOT NULL,            -- out | back
    mode TEXT NOT NULL,
    band TEXT NOT NULL,
    minutes REAL NOT NULL,
    method TEXT NOT NULL,
    version TEXT NOT NULL,
    PRIMARY KEY (apartment_id, destination_id, place_id, direction, mode, band, version)
);

CREATE TABLE setting (
    owner_id INTEGER NOT NULL REFERENCES app_user(id),
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (owner_id, key)
);
