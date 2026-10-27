# server

The API on the tailnet (FastAPI, Python 3.12 or newer). Design:
`docs/design.md` sections 2, 13 and 14. Today (M6) photos are stored as files under `<data dir>/photos/<apartment id>/` (JPEG only, 4 MB cap; `/api/apartments/{id}/photos`, `/api/photos/{id}`). Before that (M5) transit times come from a self-hosted OpenTripPlanner (`APTSCOUT_OTP_URL`; `otp.py`) when set, with the simple model as the fallback; `build-otp-inputs` prepares OTP's directory (clipped streets, the CTA feed, a build config) and `recompute` warms the cache and drops times from older data. Before that (M4) it also keeps the owner's destinations and settings and computes the weekly travel time (`weekly.py`; the simple CTA model is `transit.py`). Before that (M3) it also keeps the places and categories in SQLite (`aptscout.sqlite` in the data directory, numbered migrations in `aptscout/migrations/`) and serves `/api/categories` and `/api/places`. It serves the basemap
tiles with byte ranges, the basemap fonts and sprites, the CTA overlays
(`/api/cta/{rail,bus,stops}`), the dataset versions and the built `web/`.
Sign-in is a development stub until Pocket ID (M7): `/api/*` answers 401
unless `APTSCOUT_DEV_USER` is set.

```sh
python3 -m venv ../.venv && ../.venv/bin/pip install -r requirements.txt
../.venv/bin/python -m aptscout fetch-gtfs      # see ../data/README.md for the others
../.venv/bin/python -m aptscout fetch-osm && ../.venv/bin/python -m aptscout fetch-pools
../.venv/bin/python -m aptscout import-places
APTSCOUT_DEV_USER=me ../.venv/bin/python -m uvicorn aptscout.app:app --port 8000
```

Apartments (`/api/apartments`) carry rent, floor, facing and the rest of
design section 7, a status history and a score with its explanation. Scores
use `APTSCOUT_VALHALLA_URL` (a self-hosted Valhalla, walking) when set and a
straight line times 1.3 otherwise; `/api/geocode` uses `APTSCOUT_NOMINATIM_URL`
(a self-hosted Nominatim) and answers 503 when it is unset, so the owner drops
the pin by hand. Both services arrive with the stack (M7); until then the
clients are tested against recorded responses only.

Environment: `APTSCOUT_DATA_DIR` (runtime data, default `state/`),
`APTSCOUT_CITY` (default `chicago`, a file in `aptscout/cities/`),
`APTSCOUT_WEB_DIST` (default `../web/dist`).

Tests are in `../tests/` (standard library `unittest`, synthetic feeds and
made-up places); `../scripts/verify` runs them.

The owner's apartments, rents, rankings and notes are runtime data on the
host. They never go in the repository; test fixtures use made-up addresses.
