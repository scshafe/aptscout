-- M3: apartments, their status history and the cached category distances.
CREATE TABLE apartment (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES app_user(id),
    label TEXT NOT NULL DEFAULT '',
    address TEXT NOT NULL DEFAULT '',
    unit TEXT NOT NULL DEFAULT '',
    lat REAL,
    lon REAL,
    location_source TEXT NOT NULL DEFAULT 'none',
    rent INTEGER,
    rent_includes TEXT NOT NULL DEFAULT '',
    fees INTEGER,
    deposit INTEGER,
    beds REAL,
    baths REAL,
    sqft INTEGER,
    floor INTEGER,
    floors_in_building INTEGER,
    facing TEXT NOT NULL DEFAULT '',
    lease_months INTEGER,
    available_from TEXT,
    pets TEXT NOT NULL DEFAULT '',
    laundry TEXT NOT NULL DEFAULT '',
    parking TEXT NOT NULL DEFAULT '',
    listing_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'interested',
    notes TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL,
    updated TEXT NOT NULL
);
CREATE INDEX apartment_owner ON apartment (owner_id);

CREATE TABLE apartment_status (
    apartment_id INTEGER NOT NULL REFERENCES apartment(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    at TEXT NOT NULL
);

-- value is walking minutes to the place under `measure`; dropped when the
-- apartment or the place moves (design 4.4: only what changed is recomputed).
CREATE TABLE apartment_distance (
    apartment_id INTEGER NOT NULL REFERENCES apartment(id) ON DELETE CASCADE,
    place_id INTEGER NOT NULL REFERENCES place(id) ON DELETE CASCADE,
    measure TEXT NOT NULL,
    minutes REAL NOT NULL,
    PRIMARY KEY (apartment_id, place_id, measure)
);

CREATE INDEX place_position ON place (lat, lon);
