-- M6: photos taken while touring (files live beside the database, design 7 and 10).
CREATE TABLE apartment_photo (
    id INTEGER PRIMARY KEY,
    apartment_id INTEGER NOT NULL REFERENCES apartment(id) ON DELETE CASCADE,
    file TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    created TEXT NOT NULL
);
CREATE INDEX photo_apartment ON apartment_photo (apartment_id);
