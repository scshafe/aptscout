# aptscout: design

Status: **accepted by the owner on 2026-10-27, as written, with all 22 Owner
decisions taken as recommended.** Planned-work PRs for the milestones are
approved; a new design decision goes back to the owner. `docs/brief.md` is fixed and is the source of the
requirements; this document answers its open questions (numbers in
parentheses, such as Q4, refer to them). Every choice the owner must confirm
is collected in [Owner decisions](#owner-decisions) at the end.

Facts about outside services (URLs, licences, usage policies) are from the
designer's knowledge and must be re-checked when each is first used; M1 and
M2 include that check.

## 1. Principles

1. **Free and self-hosted first.** No paid service, account or API key
   without the owner's approval. Everything below runs on the laptop from
   open data.
2. **The owner's addresses never leave the laptop** (Q12). Geocoding,
   routing and tiles are self-hosted, so no saved address, destination or
   trip is sent to a third party. The only outbound traffic is bulk public
   data downloads (map extract, CTA feed, Overpass queries by bounding box).
3. **Public data and private data are separate.** Datasets are downloaded
   into a cache and can be rebuilt. The owner's data is in one SQLite file
   outside the repository.
4. **One user first, a second user possible.** The schema carries an
   owner column from day one, so a partner can be added without a rewrite.
5. **Small enough to run beside the other tailnet apps**: a few containers,
   the heaviest (transit routing) optional until it is needed.

## 2. Architecture

```
phone / laptop browser (tailnet)
        |  HTTPS, Pocket ID sign-in
   [ tailnet node  aptscout.<tailnet>.ts.net ]
        |
   [ web: static single page app + MapLibre ]      served by the server
   [ server: API, scoring, import jobs ]  ---- SQLite (runtime data)
        |            |             |
   [ tiles ]   [ Nominatim ]   [ routing: Valhalla (walk/bike/drive),
   PMTiles     (Chicago        OpenTripPlanner (CTA transit) ]
   file        extract)
```

Containers on the laptop (rootless docker, as `dev.toml [identity]` grants
the agent for the server image): `server` (serves the API and the built
`web/`), `valhalla`, `nominatim`, `otp` (added at M5). Tiles are one static
file read by the server, so they are not a container.

## 3. Data sources (Q1, Q2, Q3, Q4, Q6)

### 3.1 Map tiles (Q1)

Recommendation: **self-hosted vector tiles from a Protomaps PMTiles file**
cut from the OpenStreetMap extract for the Chicago region, drawn with
**MapLibre GL JS**.

- Why: OSM's own tile servers forbid heavy or bulk use and are for light
  interactive use only; a phone touring session is light, but the app also
  renders overlays constantly and the policy gives no guarantee. Hosted
  vector tile services are free only up to a quota and mostly want an API
  key (an account, so the owner must approve). A PMTiles file is a single
  static file (tens of MB for the metro area, served with HTTP range
  requests by the server), with no tile server process, no key and no
  outbound traffic.
- Attribution "© OpenStreetMap contributors" (ODbL) is shown in the map
  corner whatever the source; Protomaps' basemap style is permissive.
- Alternative: Leaflet with OSM raster tiles under the tile usage policy
  (simplest, smaller JS, but depends on a third party and its policy, and
  no vector styling for CTA overlays). Fallback if PMTiles is awkward.

### 3.2 Places (Q2)

Source: **OpenStreetMap**, imported from a local Chicago extract
(Geofabrik Illinois PBF, clipped to Chicago plus a margin) with `osmium` /
`pyosmium`, rather than live Overpass calls. A local extract is stable,
needs no usage-policy care and is reproducible; the extract refreshes
monthly. Overpass stays available as the development shortcut (small
bounding-box queries, with caching).

Shipped categories and their OSM tags (the owner can change the mapping,
see below):

| Category | OSM tags |
| --- | --- |
| Grocery | `shop=supermarket`, `shop=greengrocer` |
| Convenience store | `shop=convenience` (a separate category, hidden by default) |
| Gym | `leisure=fitness_centre`, `leisure=sports_centre` with `sport=fitness` |
| Lap pool | see 3.3 |
| Park | `leisure=park` (polygons use the centroid and nearest edge) |
| Pharmacy | `amenity=pharmacy` |
| Cafe | `amenity=cafe` |
| Library | `amenity=library` |
| Laundromat | `shop=laundry` |
| CTA rail station, CTA bus stop | from the CTA feed (3.4), not OSM |

The first milestone ships grocery, gym, lap pool and transit; the others are
data rows, added by editing the category table.

**The owner's own categories and places.** A category is a database row
(name, colour, icon, OSM tag filter or "manual only"). The owner can add a
category, add a place by hand (click the map or type an address), edit or
hide an imported place, and mark a place as a **favourite** (used by
scoring, section 6). Manual and edited places are never overwritten by an
import: imported places carry an OSM id, and a re-import only touches rows
with an OSM id that the owner has not edited (an `edited` flag), and it
reports places that disappeared instead of deleting them.

Paid place APIs (Google Places, Foursquare and so on) are not used. They
need accounts or keys and their terms usually forbid storing results.

### 3.3 Finding lap pools (Q2)

OSM is patchy here: `leisure=swimming_pool` mixes apartment-building
amenity pools, hotel pools, and public lap pools, and `sport=swimming`,
`access`, `length` and `lanes` are often missing. The design combines
sources and puts the owner in the loop:

1. **OSM candidates**: `leisure=swimming_pool` (and `leisure=sports_centre`
   / `leisure=fitness_centre` with `sport=swimming`) in the region.
2. **Score candidates** into "likely lap pool", "maybe" and "probably not":
   `access` of `private` or `residential` is dropped; `location=indoor` or
   `length` of at least 20 m or `lanes` present raises it; `swimming_pool=
   hot_tub` or `leisure=swimming_pool` inside a `building=apartments` or
   `tourism=hotel` area is dropped.
3. **Chicago Park District pools**: the City of Chicago data portal and the
   Park District's site list indoor and outdoor pools with addresses. These
   are public records, imported once as a seed file of names and addresses
   (geocoded with the self-hosted Nominatim) and merged with OSM candidates
   by name and distance (within about 100 m). Re-check the portal dataset's
   licence and columns at M2.
4. **Gym listings**: private clubs with lap pools (YMCAs, university
   facilities, health clubs) are not reliably tagged. They are covered by
   manual entry (the owner adds them), not by scraping commercial listing
   sites.
5. **Owner confirmation**: every lap pool candidate has a state:
   *unreviewed*, *confirmed*, *rejected*. The map shows unreviewed candidates
   in a muted style; only confirmed pools and (optionally) unreviewed
   "likely" ones count in scoring. The owner can add the details that matter
   (length, lanes, indoor, open hours, day-pass price) as notes.

### 3.4 CTA data (Q3)

- **Static feed**: the CTA publishes a GTFS static feed (routes, shapes,
  stops, stop times, calendar) from its developer pages. The developer
  terms (licence agreement) permit use in applications with attribution
  and a "not guaranteed accurate" disclaimer; re-read the current terms at
  M1 and record them in `data/README.md`. No key is needed for the static
  feed.
- **Use**: routes and shapes become two map overlays (rail lines coloured
  with the official line colours from `routes.txt`, bus routes thin and
  toggleable by route), stops become the "Transit stop" category, and the
  same feed is the input of OpenTripPlanner (section 4).
- **Refresh**: a weekly job fetches the feed and compares the HTTP
  `Last-Modified`/ETag and the feed's `feed_info.txt` version and
  `calendar` end dates. A changed feed is imported into a new dataset
  version; the app shows "CTA data: version X, valid to Y" in its footer
  and a banner when the feed has expired or is about to (calendar end
  date within 14 days). Travel times computed from an older feed are
  marked stale and recomputed (section 4.4).
- **Realtime** (Bus Tracker, Train Tracker): **out of scope.** Both need an
  API key (an account) and apartment hunting needs scheduled service, not
  live arrivals. Revisit only if the owner asks.
- The feed gives scheduled service; real reliability (delays, bus bunching)
  is not modelled, and the UI says so.

### 3.5 Geocoding (Q6, Q12)

Recommendation: **self-hosted Nominatim** loaded with the same Chicago/
Illinois extract as the tiles and places. The owner's candidate addresses
and the job's address are then never sent to a third party.

- Cost: an Illinois-only import needs a few GB of disk and a modest import
  time (an hour or so); a Nominatim container idles at low memory. Updates
  are monthly re-imports along with the extract.
- Alternatives: the US Census geocoder (free, no key, US addresses, but it
  is a public service that sees each address; it is accurate for Chicago
  street addresses), or the public Nominatim (policy: one request per
  second, no bulk, identify the app; it also sees each address). Both are
  acceptable only if the owner decides that sending an address to a public
  geocoder is fine (decision 8).
- **Hand correction**: every geocode result is shown on the map as a
  draggable pin; dragging sets `lat/lon` and records `location_source =
  "manual"`. A geocoder failure (or no match) never blocks saving an
  apartment: it saves the text and a "place pin on map" prompt.
- Rooftop accuracy for new construction can be poor; the draggable pin is
  the answer.

## 4. Distances and travel times (Q4, Q15)

### 4.1 Two kinds of number

- **Distance for ranking categories** (section 6): the owner chooses per
  category among *straight line* (instant, no routing), *walk distance*
  (street network) and *walk time*. Default: walk time for grocery, gym,
  pool, pharmacy; straight line for parks and cafes.
- **Weekly travel time** (section 5): a time in the chosen mode, by
  schedule for transit.

### 4.2 Routing engines

| Mode | Engine | Notes |
| --- | --- | --- |
| walk | Valhalla (pedestrian costing) | OSM street network; walking speed a setting (default 4.8 km/h) |
| bike | Valhalla (bicycle costing) | bike speed setting; uses bike lanes and avoids major roads |
| drive | Valhalla (auto costing) | free-flow speeds only: no traffic. Time of day is not modelled; the UI says "no traffic" and an optional multiplier per time band (default x1.3 at rush hour) is a setting |
| CTA transit | OpenTripPlanner 2 over the CTA GTFS plus the OSM street graph | schedule-based, time-of-day aware, walk to stop and transfers included |

Valhalla gives one-to-many matrices and isochrone-like queries, which is the
shape of the work (one apartment to many places). Valhalla could do transit
with GTFS but its transit support is less maintained, so OTP does transit.
Alternative for walk/bike/drive: OSRM, simpler and faster but one profile per
process (three containers instead of one).

Cost on the laptop (to be measured at M3/M5 and recorded here): Valhalla
tiles for Illinois a few GB on disk, modest memory; OTP 2 for Chicago needs
a JVM with roughly 2–4 GB RAM to build the graph (once per data change) and
less to serve. The heavy parts run only when needed: the owner can stop the
`otp` container and the app falls back to the simpler transit model below.

### 4.3 Transit without OTP (the simple model, Q15 alternative)

Estimate = walk to the nearest useful stop + average wait + in-vehicle time
approximated from the straight line distance at an average CTA speed (rail
about 30 km/h, bus about 15 km/h) + walk from the stop, with a transfer
penalty. It is cheap and has no routing service, but it ignores which
lines connect which places and gives wrong answers when a trip needs a
transfer or the stops are on different lines. Use it as the M3 placeholder
and as the fallback; the schedule-based result replaces it in M5.

### 4.4 Time of day and the weekly total

Each trip has a **time band**: weekday rush (7–9 am or 5–7 pm, chosen as
departure time), weekday midday, evening, Saturday, Sunday. Transit queries
use the band's representative departure time on a real weekday/Saturday/
Sunday within the current feed's validity; walking and biking ignore it;
driving uses the optional multiplier. A band may use the median of a few
departures across its window, so a missed connection does not skew one
result.

**Round trip.** The brief defines the round trip. The model computes the
outbound time at the band's time and the return time with its own optional
return band (default: the same band's mirrored time, such as an evening
return after a morning commute). A trip's cost is outbound + return.

**Recompute cost and caching.** One time entry is
`(apartment, destination place, mode, time band) -> minutes`. They are
computed lazily and cached in the database with the data versions they came
from (`osm_version`, `gtfs_version`). A change invalidates only what it
touches:

- new apartment: its entries for every destination (a handful of routing
  calls, a second or two);
- changed trip count: nothing to recompute (the count is a multiplier);
- changed mode or band of a destination: that destination's entries for all
  apartments;
- changed destination place: that destination's entries for all apartments;
- new GTFS or OSM version: everything, in a background job, with the old
  numbers marked stale and shown until replaced.

For ten to fifty apartments and ten destinations this is a few hundred
routing calls, seconds to a minute, and the UI shows partial results as they
arrive (progress shown per column).

## 5. Weekly travel time model (Q15, Q16)

Core feature. Entities:

- **Destination**: a name, a `kind` and a `trips_per_week` (a number, may be
  fractional such as 0.5), a `mode` (walk, bike, drive, transit), a
  `time_band` (and an optional return band), and either
  - `kind = place`: a specific place (such as the job; entered by address,
    stored privately), or
  - `kind = category`: "any grocery store", with a **selection rule**
    (Q16, below).
- **Per-apartment result**: for each destination, the one-way times, the
  round trip, `trips_per_week x round trip`, and the chosen place for a
  category destination.

**Weekly total** for an apartment = the sum over destinations of
`trips_per_week x (outbound + return)` minutes. It is shown as hours and
minutes per week, with the breakdown per destination (the "where does the
time go" view).

**Which place does a category trip use** (Q16). The rule is chosen per
destination, default "best":

1. *best by travel time in the chosen mode* (default): among the
   candidates inside a pre-filter (the 10 nearest by straight line, and
   within the category's maximum distance), the one with the shortest
   round-trip time; this is what the owner really does when shopping
   nearby, and it can differ from the nearest by straight line;
2. *nearest by straight line*: cheapest to compute, a fine approximation for
   walking;
3. *a favourite*: the owner's chosen place (their gym), ignoring others;
4. *average of the nearest N* (N is a setting): for when the owner varies
   between several stores.

Because a destination's mode is its own, the same apartment can score walk
5 min to the gym and 35 min by transit to work; no mode is global.

**Minimise.** The app ranks apartments by ascending weekly total, with the
breakdown, and offers a "what-if" panel: change trips per week or a mode
and see the order change at once (the cache makes a trip-count change
instant). Optional **sensitivity**: show the weekly total at +/- 20% trips
for the top apartments, so the owner sees whether a ranking is robust.
A time budget per destination ("work at most 40 min each way") filters
apartments without removing them, and marks them with a warning.

## 6. Ranking and scoring (Q5, Q17)

### 6.1 Per-category score (0–100)

Each category has:

- a **weight** (the owner's rank, entered as a 0–10 importance slider, with
  a drag-to-order list for a quick start: position 1 gets 10 and so on, and
  the owner may edit numbers);
- a **distance measure** (straight, walk distance, walk time, section 4.1);
- a **target** `d_good` (full marks within this, default 5 min walk) and a
  **maximum** `d_max` (zero beyond this, default 20 min walk);
- an **aggregation**: nearest one, mean of the nearest N, or "a favourite
  only" (when a favourite is set it counts instead of the nearest of the
  kind, or alongside it; the owner chooses).

The category score is a decreasing curve between the target and the
maximum (linear by default; a smooth option is a setting), so nearest-only
and nearest-N differ only in the number used for the distance. A category
with nothing inside `d_max` scores 0 and is reported as "none within X".

### 6.2 Combined score

Two numbers, never hidden inside one another:

1. **Place score** = weighted mean of category scores (weights as above).
2. **Weekly travel time** (section 5), in minutes per week.

The comparison shows both, plus **rent**, as separate sortable columns
(Q17's third option), and offers a **combined score** the owner can switch
on: `combined = w_place x place_score + w_time x time_score + w_rent x
rent_score`, where `time_score` and `rent_score` are min–max scaled to 0–100
over the apartments currently shown (lower is better), and the three
weights are sliders. Default: combined is off; the table is sorted by weekly
time with place score and rent visible. Reason: the owner's stated core goal
is minimising weekly time, and a single number hides trade-offs; but a
single number is handy when comparing twenty places.

**Hard filters** (never scored, they hide or grey out): maximum rent,
minimum beds, status, and the per-destination time budgets of section 5.

### 6.3 Explaining a score

Every score has a "why" panel: per category the chosen place, its distance/
time, its sub-score and its weight contribution ("Grocery: Store X, 6 min
walk, 92 x weight 8 = 40% of the place score"). The map draws lines from
the selected apartment to the places it counts. Weights and thresholds are
edited in one settings page, and the table updates live.

## 7. Data model (Q6, Q10)

SQLite, one file; tables (names illustrative, columns the point):

- `user(id, oidc_subject, name)`
- `category(id, owner_id, key, name, colour, icon, weight, measure, d_good,
  d_max, aggregation, builtin, visible)` (the shipped categories are copied
  to each owner at first sign-in; the OSM tag mapping lives in code)
- `place(id, category_key, owner_id, ext_id, source, name, lat, lon, address,
  lap_score, also, edited, gone, notes)`: imported rows have no owner and an
  `ext_id` (`osm:n123`, `cta:40001`, `pd:...`); the owner's own places carry
  the owner
- `place_mark(owner_id, place_id, state [unreviewed/confirmed/rejected],
  favourite, hidden, notes)`: the owner's view of a place
- `apartment(id, owner_id, label, address, unit, lat, lon, location_source,
  rent, rent_includes, fees, deposit, beds, baths, sqft, floor,
  floors_in_building, facing, lease_months, available_from, pets, laundry,
  parking, listing_url, status, notes, created, updated)`
- `apartment_photo(id, apartment_id, file, caption)` (optional, M6)
- `destination(id, owner_id, name, kind, place_id|null, category_id|null,
  selection_rule, n, trips_per_week, mode, time_band, return_band,
  max_minutes)`
- `travel_time(apartment_id, destination_id, place_id, direction, mode,
  band, minutes, osm_version, gtfs_version, computed_at)`
- `dataset_version(name, version, fetched_at, valid_to)` for OSM, GTFS and
  the Park District seed.
- `settings(owner_id, key, value)` (speeds, multipliers, combined weights)

**Apartment fields (Q6).** Address, unit; **rent** (monthly, plus fees,
what is included such as heat, and a computed "effective rent"); beds, baths,
square feet; **floor** and floors in building; **facing**: one of N, NE, E,
SE, S, SW, W, NW (a compass picker; a unit with windows on two sides takes
two values, stored as a set), and a derived hint "morning sun" for east
and so on; lease length, available date, pets, in-unit laundry, parking,
listing link, free notes; **status**: *interested*, *contacted*, *toured*,
*applied*, *rejected*, *signed*, with a date of each change; photos optional
(stored as files beside the database, resized on upload; skipped if the owner
does not want them at M6). A listing link is stored as a link only; the app
does not scrape listing sites.

The app is Chicago first, with city-specific data (extract, GTFS) behind a
`city` setting (Q14), see section 11.

## 8. User interface (Q7, Q9)

### 8.1 Layout

Desktop: the **map** on the left (about 60%), the **comparison table** on
the right; selecting a row flies the map to the apartment, selecting a pin
highlights the row. A divider lets the owner enlarge either.

- **Map layers** (toggle panel): categories (colour/icon each, with a
  legend), CTA rail lines, CTA bus routes (all off by default, "show
  routes near the selected apartment" on), apartments (pin colour = status,
  label = rent), isochrone-style "walk 10 min" circle for the selected
  apartment, lines to the counted places.
- **Comparison table**: one row per apartment; columns: rent, beds/baths,
  floor, facing, status, **weekly travel time**, place score, per-category
  distance columns (choose which), combined score (if on), notes
  indicator. Sort on any column; filter chips for status, rent range,
  beds, facing; the cheapest/best value in each numeric column is
  highlighted, and a column shows the difference from the top (for example
  "+12 min/week"). Pick two to four apartments for a **side-by-side**
  card view (the same fields vertically, differences highlighted).
- **Weekly time view**: per apartment a stacked bar (job, grocery, gym ...)
  showing the minutes per week, and the what-if panel (section 5).
- **Settings**: categories and weights, destinations and trips per
  week, speeds and multipliers.

### 8.2 Phone use (Q9)

The app is a responsive PWA (installable, a manifest, a service worker that
caches the shell and the last data so it opens in a building with bad
signal). The tailnet is required for sign-in and data; offline, the app
shows the cached data read-only and **queues new apartments** to sync when
it reconnects. On a phone:

- The layout is a full-screen map with a bottom sheet (list/detail); the
  table becomes cards.
- **Add on the spot**: one tap on "+", then "use my location" (browser
  geolocation, which needs HTTPS: the tailnet node provides it), or type an
  address; the form asks only rent, unit, floor, facing (compass picker,
  large tap targets), status, and a note; everything else is optional later.
  A camera button attaches photos (M6).
- The facing picker can use the phone compass (`DeviceOrientation`) as a
  convenience, behind a button, not by default.

### 8.3 Accessibility

Colour is never the only carrier (icons and labels), controls are
keyboard-reachable on desktop, and map pins have text alternatives in the
table.

## 9. Sign-in and users (Q8)

**Pocket ID** (OIDC, as the other tailnet apps): the server is an OIDC
relying party using the authorization-code flow with PKCE; session in a
secure, http-only cookie. The owner session registers the Pocket ID client
and sets its client id/secret in the deploy environment (not an agent job).
Tailnet access control stays the outer gate.

Single user at launch, with an `owner_id` on every private table (section 7)
so a partner can be added: **v1 gives each user a private set**, and sharing
an apartment list with a partner is a later option ("shared workspace", each
member adds apartments and notes, with their own destinations, since their
jobs differ). Recommendation: start single user, keep the column, decide
sharing when it is asked for (decision 9).

## 10. Storage, backup and export (Q10)

- **Where**: `/srv/aptscout/` style data directory on the laptop (path set
  by the owner session in the stack), mounted into the `server`
  container: `aptscout.sqlite` (WAL mode), `photos/`, `cache/` (downloaded
  datasets, rebuildable), `tiles/` (PMTiles), `routing/` (Valhalla/OTP
  graphs, rebuildable). Only `aptscout.sqlite` and `photos/` are the
  owner's irreplaceable data.
- **Database**: SQLite, because one user, one writer, small data, no extra
  service to run or secure; schema migrations are numbered SQL files applied
  at start. PostgreSQL/PostGIS is the alternative when many users or heavy
  spatial queries appear; the distances are computed by the routing engines
  and plain haversine, so SQLite is enough.
- **Backup**: a nightly job uses SQLite's online backup (`.backup` /
  `VACUUM INTO`) to write a dated copy in a backup directory, keeps 14 daily
  and 6 monthly copies, and also copies `photos/`. The backup directory
  should be on a different disk or synced by the owner's existing backup
  tooling (the owner session decides where; the agent cannot reach the
  laptop). A `restore` command in the server's CLI restores a copy and runs
  the integrity check (`PRAGMA integrity_check`). A restore is rehearsed in
  M7.
- **Export**: a button/endpoint downloads the owner's data as one JSON file
  (apartments, destinations, categories, weights, places the owner added or
  edited) and a CSV of the comparison table. Import of the same JSON makes
  migration and a fresh install easy. Exports are downloaded by the owner;
  they are never committed.

## 11. Chicago only or any city (Q14)

Chicago first, with **no city names hard-coded in logic**: the extract
boundary, GTFS source URL, the Park District seed and defaults are in a
`city` configuration file (`data/` documents the shape; the files are
fetched into the cache, not committed). Adding a city is then: a new
config, another extract and its GTFS feed. Other cities' transit feeds
often need a key or have other terms; that stays out of scope until asked.
Recommendation: keep it Chicago-only in the UI for v1, with the config
separation as a cheap preparation.

## 12. Privacy (Q12)

The owner's private data: apartments (addresses, rents, notes, photos),
destinations (the job's address and the weekly trips), rankings,
favourites, the travel-time cache, and anything derived. Rules:

- Stored only in the runtime data directory on the laptop; not in the
  repository, fixtures, issues, PRs or CI logs (`tests/test_repository.py`
  already enforces no database/backup/`.env` and no tailnet name).
- **Everything that sees an address is self-hosted** (Nominatim, Valhalla,
  OTP, tiles from a local file). The browser requests tiles from the same
  origin, so even tile fetches do not reveal which area the owner looks at.
  Recommendation, decision 8.
- **Logs**: the server logs request method, path template and status, never
  query strings or bodies that contain addresses; routing and geocoder
  requests are logged without coordinates. No third-party analytics, fonts
  or CDNs in the web app (fonts and libraries are bundled).
- **Fixtures and tests** use made-up addresses on real-looking but fictional
  streets in an invented neighbourhood, and small synthetic GTFS/OSM
  files.
- Public datasets (OSM, CTA) are not private and may be cached anywhere,
  but the cache is not committed either (size, licence hygiene).
- Dependencies: pinned versions, no telemetry.

## 13. Stack (Q13)

- **server**: Python 3.12 with **FastAPI**, SQLite via the standard library
  (`sqlite3`) and plain SQL migrations, `httpx` to call Valhalla/OTP/
  Nominatim, a small job runner (a thread pool plus a `job` table; no Celery/
  Redis). Chosen because the repository's verify already uses Python, the
  data work (GTFS, scoring) is easy in Python, and the load is a single user.
  Tests with the standard library's `unittest` plus FastAPI's test client, so
  `scripts/verify` stays dependency-light.
- **web**: **TypeScript** with Vite, **MapLibre GL JS** (with the PMTiles
  protocol plugin) and **Svelte** (small bundle, good on phones). The
  built files are served by the server, so one container serves both.
  Alternative: React (bigger ecosystem, bigger bundle) or no framework at
  all (plain TS modules; fine for the first milestone).
- **Import tools**: Python scripts in `server/` driven by `make`-style
  subcommands (`aptscout import-osm`, `import-gtfs`, `build-tiles`),
  using `osmium` and the `pmtiles`/`tippecanoe`/Planetiler tools in a
  tools container, not in the runtime image.
- Lint/format: ruff, mypy light; Prettier and `svelte-check` for the web.
  `scripts/verify` runs them as they appear.

## 14. Deploy (Q11)

- **Lane**: `dev.toml [deploy] lane = "none"` now. When the owner accepts the
  design, the owner session sets it to `runner` (a deploy workflow on the
  self-hosted runner of the laptop, reviewed by hand), registers the runner,
  creates the infra stack and the tailnet node, and registers the Pocket ID
  client. None of these are the agent's work; the PR lists exactly what is
  needed.
- **Stack under infra**: services `server`, `valhalla`, `nominatim`,
  `otp`, with volumes for the data directory (section 10). The image build
  (`server` + built `web`) runs in CI on the public repository; the images
  are published to GHCR (free for public repos) or built on the runner;
  decision 10.
- **External datasets on the host**: a `datasets` job (a compose profile run
  by the owner's scheduler, or an in-app weekly job) downloads the Illinois
  extract (Geofabrik), cuts the Chicago region, builds PMTiles, the
  Nominatim database, the Valhalla tiles and the OTP graph, and fetches the
  CTA GTFS. It writes to the data directory, versions each dataset in
  `dataset_version`, and swaps in new files atomically. These steps need
  outbound internet on the laptop and some GB of disk and CPU time for the
  first build; `data/README.md` records each source, its licence and the
  command. Large files are never committed.
- **Health**: `/healthz` for the stack; the app shows dataset versions and
  the CTA feed validity (3.4).
- **Updates**: a merge to `main` redeploys through the runner lane; datasets
  update independently of the code.
- Re-check resource use before going live: the heaviest parts (OTP, the
  Nominatim import) may share the laptop with other apps.

## 15. Milestones (Q18)

Each milestone is a PR (or a few), verified by `./scripts/verify` and
`dev check .`, with CI green, and gives something the owner can use.

- **M0 design** (this PR): owner accepts and answers the decisions.
- **M1 map and CTA**: server and web skeleton, PMTiles basemap with MapLibre,
  CTA rail and bus overlays from GTFS, the dataset fetch commands, the
  attribution and `data/README.md` sources. Sign-in with a development stub.
- **M2 places**: OSM import, the shipped categories, lap pool candidates
  with the Park District seed and the confirm/reject flow, manual places and
  categories, favourites.
- **M3 apartments and distances**: apartment CRUD with all fields, the
  geocoder, draggable pin, straight-line and walk distance (Valhalla),
  category scoring and the "why" panel, the comparison table, filters, side
  by side.
- **M4 weekly travel time, simple model**: destinations, trips per week,
  modes and bands, the weekly total with the simple transit estimate, the
  what-if panel, rank by weekly time, the combined score switch.
- **M5 schedule-based transit**: OTP over the CTA feed, replacing the simple
  estimate, time bands, feed refresh and stale handling.
- **M6 phone and polish**: PWA, offline queue, add-on-the-spot, optional
  photos, compass facing.
- **M7 deploy and operations**: Pocket ID, the runner lane, the stack,
  backups with a rehearsed restore, export/import. (Deploy pieces needing
  the owner session are requested in the M1 PR already so they are ready.)

## 16. Risks and unknowns

- OTP's memory and graph build time on the laptop: measure early (M3 spike);
  fallback is the simple model.
- Lap pool data quality: mitigated by the manual confirm flow; accept some
  manual work.
- Geocoding of new buildings: the draggable pin.
- CTA feed changes (format, expiry): the refresh check and banner.
- Schedule-based times are scheduled, not real: the UI says so.
- Scope: the weekly-time feature and the combined score are the heart of the
  app; photos, compass, and multi-user sharing are the first things to cut.

## Owner decisions

Each row: my recommendation first, the main alternative second. The brief's
question number is in the first column's parentheses.

| # | Decision | Recommendation | Main alternative | Outcome |
| --- | --- | --- | --- | --- |
| 1 | Map tiles and library (Q1) | Self-hosted Protomaps PMTiles with MapLibre GL JS | Leaflet with OSM's raster tiles under their usage policy (simpler, third-party dependent) | Accepted (recommendation) |
| 2 | Place data source (Q2) | OSM from a local Geofabrik extract, refreshed monthly | Live Overpass queries (no extract to manage; rate-limited, less reproducible) | Accepted (recommendation) |
| 3 | Lap pool method (Q2) | OSM candidates + Park District seed + owner confirm/reject, others added by hand | OSM only, plus manual entry (less setup, more manual work) | Accepted (recommendation) |
| 4 | First categories and owner-defined ones (Q2) | Grocery, gym, lap pool, transit first; others (park, pharmacy, cafe, library, laundromat) as rows; owner can add categories and places | Fixed list in v1, custom categories later | Accepted (recommendation) |
| 5 | CTA data and realtime (Q3) | Static GTFS only, weekly refresh check with an expiry banner; no realtime | Add Bus Tracker/Train Tracker later (needs API keys, an account) | Accepted (recommendation) |
| 6 | Distance measure (Q4) | Per category: walk time by default, straight line for parks/cafes | Straight line everywhere (no routing service) | Accepted (recommendation) |
| 7 | Routing engines (Q4, Q15) | Valhalla for walk/bike/drive; OpenTripPlanner 2 on the CTA GTFS for transit (M5), simple model first | Simple transit model only; or OSRM instead of Valhalla | Accepted (recommendation) |
| 8 | Privacy: may the owner's addresses go to outside services? (Q12) | No: self-hosted Nominatim, Valhalla, OTP, tiles | Allow the US Census geocoder or public Nominatim for geocoding (less to run) | Accepted (recommendation) |
| 9 | Users and sharing (Q8) | Pocket ID, single user, `owner_id` kept so a partner can be added | Two users with a shared workspace from the start | Accepted (recommendation) |
| 10 | Time of day and round trips (Q15) | Per-trip time band, a return band, median over a few departures; drive free-flow with an optional multiplier | One fixed weekday-morning time for everything | Accepted (recommendation) |
| 11 | Which place a category trip uses (Q16) | Best by travel time among the 10 nearest, per-destination choice of nearest, favourite or mean of N | Always the nearest by straight line | Accepted (recommendation) |
| 12 | Weekly time versus rankings and rent (Q5, Q17) | Separate sortable columns, default sort by weekly time; an optional combined score with three sliders | One combined score always on; or weekly time only with the rest as filters | Accepted (recommendation) |
| 13 | Category scoring (Q5) | Weight 0–10, target and maximum distance per category, nearest or nearest N or favourite | Rank-order only (no thresholds) | Accepted (recommendation) |
| 14 | Apartment fields and statuses (Q6) | The field list in section 7 including facing as a set of compass points; status interested/contacted/toured/applied/rejected/signed; photos optional at M6 | Fewer fields in v1, no photos | Accepted (recommendation) |
| 15 | Geocoder (Q6) | Self-hosted Nominatim with a draggable pin | US Census geocoder | Accepted (recommendation) |
| 16 | Phone use (Q9) | Responsive PWA with offline cache and queued add-on-the-spot | Responsive web page only, online | Accepted (recommendation) |
| 17 | Storage and backup (Q10) | SQLite in the laptop's data directory, nightly online backup (14 daily, 6 monthly) to a place you name, JSON/CSV export | PostgreSQL/PostGIS; or backups left to your existing tooling | Accepted (recommendation) |
| 18 | Stack (Q13) | Python/FastAPI server; TypeScript, Vite, Svelte and MapLibre web | Node/TypeScript end to end; or React for the web | Accepted (recommendation) |
| 19 | Chicago only? (Q14) | Chicago-only in the UI, city settings in a config for later | Multi-city from the start | Accepted (recommendation) |
| 20 | Deploy (Q11) | Runner lane, stack with server/valhalla/nominatim/otp, images from CI to GHCR (free) or built on the runner; you do the runner, node, Pocket ID client and stack | Build and run on the laptop by hand until later | Accepted (recommendation) |
| 21 | Laptop resources (Q4, Q15) | Accept ~4 GB RAM and a few GB disk for routing and geocoding, measured at M3/M5 | Cap resources: simple models only, no OTP | Accepted (recommendation) |
| 22 | Milestones (Q18) | M0–M7 as in section 15, with travel time at M4/M5 | Reorder: weekly time before the apartment table | Accepted (recommendation) |
