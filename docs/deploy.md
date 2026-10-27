# Deploying aptscout

What is built (by the project agent, in this repository) and what only the owner
session can do. Design: `docs/design.md` section 14.

## Built and tested

- `Dockerfile`: the server image (the API, the dataset tools, the built web app),
  non-root, `/data` volume, `/healthz` health check. Built and smoke-tested with
  rootless docker during M7.
- `deploy/compose.yml`: the proposed stack: `server`, `jobs`, `nominatim`,
  `valhalla`, `otp`. A proposal, not tested end to end (see below).
- `deploy/deploy.workflow.yml.example`: a draft runner-lane workflow.
- Pocket ID sign-in (`server/aptscout/auth.py`), backup/restore/retention
  (`backup.py`), the scheduler (`jobs.py`), export/import (`export_api.py`).

## Owner steps (nothing here is done by the agent)

1. **Runner registration**: register a self-hosted runner for `scshafe/aptscout`
   on the laptop; set its labels in the workflow.
2. **Tailnet node**: add `aptscout.<tailnet>.ts.net` in front of the `server`
   container (HTTPS; the service worker and geolocation need it).
3. **Pocket ID client**: create an OIDC client with redirect URI
   `https://aptscout.<tailnet>.ts.net/auth/callback`; give the stack its issuer,
   client id and client secret. Generate `APTSCOUT_SESSION_SECRET`
   (`openssl rand -hex 32`). Optionally set `APTSCOUT_ALLOWED_SUBJECTS` to the
   OIDC subject(s) allowed in.
4. **Stack review**: turn `deploy/compose.yml` into the infra stack. Decide the
   host paths (`APTSCOUT_HOST_DATA`, `APTSCOUT_HOST_SERVICES`), pin the
   `valhalla` image (it is `latest` in the draft), and check the laptop has the
   RAM and disk the design estimated (about 4 GB RAM for OTP and Nominatim, a few
   GB of disk).
5. **Backup destination**: choose where backups go (`APTSCOUT_HOST_BACKUP`),
   ideally another disk or a location your existing backup covers.
6. **Flip the lane**: `dev.toml [deploy] lane = "runner"` (and `stack`/`host`),
   and place the workflow at `.github/workflows/deploy.yml`.
7. Nothing in this design costs money. If anything in the stack would, stop.

## First run on the host

```sh
# data directory, as the container user (uid 10001)
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout fetch-gtfs
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout fetch-osm
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout fetch-pools
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout fetch-assets
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout import-places
# tiles need the `pmtiles` tool (go-pmtiles): install a pinned release on the host and
# run `python -m aptscout build-tiles` where it is on PATH
docker compose -f deploy/compose.yml run --rm jobs python -m aptscout build-otp-inputs
# build the OTP graph once, then serve it
docker compose -f deploy/compose.yml run --rm otp --build --save
docker compose -f deploy/compose.yml up -d
```

Nominatim and Valhalla import the Illinois extract themselves on first start
(minutes to an hour). After a new CTA feed: `build-otp-inputs`, rebuild the OTP
graph, then `recompute`.

## Backup and restore

`python -m aptscout backup` (the `jobs` service runs it nightly) writes a dated
SQLite copy, mirrors photos, and keeps the newest copy of each of the last 14
days and of each of the 6 months before. To restore: stop `server`, then
`python -m aptscout restore <file>` (the current database is kept aside as
`aptscout.sqlite.before-restore-<time>`), start `server`. Rehearse this once
before relying on it; the test suite does it on a scratch database.

## Not verified by the agent

The agent cannot reach the laptop, the tailnet or a Pocket ID instance, and has
not run the Nominatim, Valhalla or OTP containers. Their configuration in
`compose.yml` follows each image's documented usage and needs a first-run check
by the owner: the clients are tested against mocked responses only.
