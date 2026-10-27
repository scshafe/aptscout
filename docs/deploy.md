# Deploying aptscout

aptscout runs on the laptop as an app-owned stack on the runner lane (scshafe
infra `docs/platform/agent-deploy.md`), at `https://aptscout.<tailnet>/`,
tailnet only. A merge to `main` deploys it: the `deploy` workflow verifies on
GitHub, then the laptop's runner (`laptop-aptscout-prod`) calls the host's
entrypoint, which backs up, builds the `Dockerfile` at the merged commit and
brings up `deploy/stack/`; a health job checks the result. Watch a deploy with
`gh run watch`; roll back by merging a revert, or dispatch `deploy.yml` with
`sha=<older commit on main>` and `allow_rollback=true`. Design: `docs/design.md`
section 14.

## The stack (`deploy/stack/`)

| Service | Container | What |
| --- | --- | --- |
| `ts-aptscout` | `ts-aptscout` | The tailnet node `aptscout`: HTTPS on 443 to the app (`serve.json`), no Funnel |
| `aptscout` | `aptscout` | The app (this repository's image) on `127.0.0.1:8000` in the node's namespace |
| `jobs` | `aptscout-jobs` | The same image running `python -m aptscout jobs`: nightly backup, weekly CTA feed, monthly OSM extract, Park District list and basemap tiles |
| `nominatim` | `aptscout-nominatim` | Geocoding (mediagis/nominatim 5.3.2), imports the Illinois extract on its first start |
| `valhalla` | `aptscout-valhalla` | Walking, bike and drive times (valhalla-scripted 3.9.1), builds its tiles from the Illinois extract on its first start |
| `otp` | `aptscout-otp` | Transit times (OpenTripPlanner 2.10.0): builds its graph from `cache/otp` when there is none or the inputs are newer (it re-checks every five minutes), then serves it |
| `tiles` | `aptscout-tiles` | The `pmtiles` CLI (go-pmtiles 1.31.2), profile `tools`: never started by a deploy; the same pinned binary is in the app image, so this is only for a manual cut: `docker compose run --rm -T tiles extract https://build.protomaps.com/<YYYYMMDD>.pmtiles /cache/tiles/city.pmtiles.part --bbox=-88.0,41.6,-87.5,42.1`, then rename the file |

Every image is pinned by version and digest; the app's own image is built from
the merged commit. The host's `tools/stack` validates the compose file against
its allowlist before anything runs, and `dev check` runs the same validator.

Sign-in: the app is its own OpenID Connect client of the platform's Pocket ID
(`server/aptscout/auth.py`), client `aptscout`, redirect
`https://aptscout.<tailnet>/auth/callback`, and admits only the subjects in
`APTSCOUT_ALLOWED_SUBJECTS`. The values live in the host's `.env`; `stack.toml
[env]` names them. `GET /healthz` (no data) is the deploy witness.

State, under the runtime directory on the laptop:

| Path | Holds | Backed up |
| --- | --- | --- |
| `state/data` | `aptscout.sqlite`, `photos/` (the owner's data) | yes |
| `state/backup` | the jobs service's nightly SQLite copies and photo mirror (`backup.py`: 14 daily, 6 monthly) | yes |
| `state/cache` | downloaded and built datasets, mounted at `<data dir>/cache`; `cache/otp` is OTP's base directory | no (rebuildable) |
| `state/nominatim`, `state/valhalla` | the routing and geocoding stores | no (rebuildable) |

The platform's `stack-backup@aptscout` (nightly, and before every deploy)
archives `state/data`, `state/backup`, `.env` and the node identity
(`stack.toml [backup]`), and the PC pulls the archives offsite.

## First run (owner, once, after the first deploy)

Nominatim and Valhalla import the Illinois extract by themselves (an hour or
more for Nominatim). The jobs service fetches the CTA feed, the OSM extract and
the Park District list and imports the places on its first start. The basemap is cut by the jobs service on its first start and then
monthly (the image carries the pinned go-pmtiles). The rest is run in the
runtime directory on the laptop, as the stack's owner:

```sh
docker exec aptscout-jobs python -m aptscout fetch-assets     # basemap fonts and sprites
# OTP: the jobs service writes its inputs once it has the CTA feed and the OSM extract
# (`build-otp-inputs`), and the otp container then builds its graph (minutes) and serves it
docker exec aptscout python -m aptscout recompute              # once OTP and Valhalla answer
```

After a new CTA feed or OSM extract nothing is run by hand. The jobs service
imports the weekly feed (and the monthly extract) and runs `build-otp-inputs`;
the otp container checks every five minutes, and when an input is newer than
its graph it stops serving, rebuilds (a few minutes, during which the app uses
its labelled simple transit model) and serves the new graph. Travel times from
the old graph are never shown: the cache key carries the graph's build time.
`docker exec aptscout python -m aptscout recompute` only warms the cache.

## Restore

From the app's own nightly copies: stop `aptscout`, then
`docker exec aptscout-jobs python -m aptscout restore <aptscout-YYYYMMDD-HHMMSS.sqlite>`
(the current database is kept aside as `aptscout.sqlite.before-restore-<time>`),
start `aptscout`. From the platform's archives: infra `backup/README.md`
(state paths owned by the app's uid are restored as root).
