-- M2: users, categories and places (docs/design.md section 7).
-- Imported places are public data (owner_id NULL); the owner's own places,
-- categories and marks (state, favourite, hidden, notes) are private.
CREATE TABLE app_user (
    id INTEGER PRIMARY KEY,
    subject TEXT NOT NULL UNIQUE,
    name TEXT
);

CREATE TABLE category (
    id INTEGER PRIMARY KEY,
    owner_id INTEGER NOT NULL REFERENCES app_user(id),
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    colour TEXT NOT NULL,
    icon TEXT NOT NULL DEFAULT '',
    builtin INTEGER NOT NULL DEFAULT 0,
    visible INTEGER NOT NULL DEFAULT 1,
    weight REAL NOT NULL DEFAULT 5,
    measure TEXT NOT NULL DEFAULT 'walk_time',
    d_good REAL NOT NULL DEFAULT 5,
    d_max REAL NOT NULL DEFAULT 20,
    aggregation TEXT NOT NULL DEFAULT 'nearest',
    UNIQUE (owner_id, key)
);

CREATE TABLE place (
    id INTEGER PRIMARY KEY,
    category_key TEXT NOT NULL,
    owner_id INTEGER REFERENCES app_user(id),
    ext_id TEXT UNIQUE,
    source TEXT NOT NULL,
    name TEXT NOT NULL,
    lat REAL NOT NULL,
    lon REAL NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    lap_score TEXT,
    also TEXT NOT NULL DEFAULT '',
    edited INTEGER NOT NULL DEFAULT 0,
    gone INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT ''
);
CREATE INDEX place_category ON place (category_key);

CREATE TABLE place_mark (
    owner_id INTEGER NOT NULL REFERENCES app_user(id),
    place_id INTEGER NOT NULL REFERENCES place(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'unreviewed',
    favourite INTEGER NOT NULL DEFAULT 0,
    hidden INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (owner_id, place_id)
);
