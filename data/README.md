# data

The external datasets aptscout uses. Nothing is committed here: datasets are
downloaded or built on the host that runs the app into
`<data dir>/cache/` (`APTSCOUT_DATA_DIR`, default `state/`, gitignored), and
this directory holds only this README (`.gitignore` and
`tests/test_repository.py` enforce it). Design: `docs/design.md` section 3.

Each dataset records its version and fetch time in `cache/datasets.json`
(`python -m aptscout status` prints it). Run the commands from `server/`
with the virtualenv (`scripts/verify` creates `.venv`).

| Dataset | Command | Source | Licence / terms |
| --- | --- | --- | --- |
| CTA overlays (rail, bus, stops) | `fetch-gtfs`, `import-gtfs` | CTA GTFS static feed (URL in `server/aptscout/cities/chicago.json`) | CTA Developer License Agreement, below |
| Basemap tiles | `build-tiles` | Region cut (`bbox` in the city file) from the public Protomaps daily build, with the `pmtiles` tool | OpenStreetMap, ODbL: "© OpenStreetMap contributors" is shown on the map |
| Basemap fonts and sprites | `fetch-assets` | `protomaps/basemaps-assets` at the commit pinned in the city file | Fonts: Noto Sans (SIL OFL); sprites and scripts MIT. Served by the app, so the browser contacts no outside host |

`fetch-gtfs` sends `If-None-Match` with the stored ETag, so an unchanged feed
is not downloaded again. The footer shows "CTA schedule valid to <date>" from
the feed's calendar and warns when the feed expires within 14 days or has
expired. Run it weekly (the host's scheduler; M7).

`build-tiles` needs the `pmtiles` command line tool
([go-pmtiles](https://github.com/protomaps/go-pmtiles)) on `PATH`. The app
does not download and run it; the host installs a pinned release (the stack's
tools image, M7).

## CTA Developer License Agreement

The feed ships `developers_license_agreement.htm`; the terms the design must
respect (re-read them when they change):

- The licence is for "assisting mass transportation riders or in furtherance
  of promoting public transportation". Using the lines to judge where to
  live by transit access is the owner's call; it is raised in the PR for M1.
- The app must not express or imply affiliation with or endorsement by CTA,
  and uses no CTA marks in its name. The footer says it is not affiliated.
- A credit line is optional; the app shows "Data provided by Chicago Transit
  Authority".
- Caching is allowed and the data must be kept reasonably up to date (the
  weekly refresh); CTA Data is not sold on its own and is not redistributed:
  it stays in the cache, never in this repository.
- Realtime (Bus Tracker, Train Tracker) is out of scope (design 3.4).

Never put the owner's apartments, rents, rankings or notes here: they are the
app's runtime data on the laptop, outside the repository.
