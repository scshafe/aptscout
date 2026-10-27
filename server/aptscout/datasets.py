"""Fetch and build the external datasets into the cache (design section 14).

Everything lands under `<data dir>/cache/`, is rebuildable and never
committed. Each dataset records its version in `datasets.json` so the app can
show it and notice an expired feed.
"""

import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx

from . import config, db, gtfs, importer

USER_AGENT = "aptscout/0.1 (self-hosted apartment map; +https://github.com/scshafe/aptscout)"
EXPIRY_WARNING_DAYS = 14


def _versions_path() -> Path:
    return config.cache_dir() / "datasets.json"


def read_versions() -> dict:
    try:
        return json.loads(_versions_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def record(name: str, **info) -> None:
    versions = read_versions()
    versions[name] = {**info, "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = _versions_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(versions, indent=2, sort_keys=True), encoding="utf-8")


def feed_status(valid_to: str | None, today: date | None = None) -> str:
    """'ok', 'expiring' (within 14 days) or 'expired' for the footer banner."""
    if not valid_to:
        return "unknown"
    today = today or date.today()
    end = date.fromisoformat(valid_to)
    if end < today:
        return "expired"
    if end - today <= timedelta(days=EXPIRY_WARNING_DAYS):
        return "expiring"
    return "ok"


def _download(client: httpx.Client, url: str, dest: Path, headers: dict | None = None) -> httpx.Headers | None:
    """Stream url to dest atomically. None when the server says 304 Not Modified."""
    with client.stream("GET", url, headers=headers or {}, follow_redirects=True) as resp:
        if resp.status_code == 304:
            return None
        resp.raise_for_status()
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + ".part")
        with open(tmp, "wb") as handle:
            for chunk in resp.iter_bytes(1 << 20):
                handle.write(chunk)
        tmp.replace(dest)
        return resp.headers


def fetch_gtfs(city: dict, force: bool = False) -> str:
    """Download the CTA feed (conditional on its ETag) and rebuild the overlays."""
    cta_dir = config.cache_dir() / "cta"
    zip_path = cta_dir / "google_transit.zip"
    prev = read_versions().get("cta_gtfs", {})
    headers = {}
    if not force and zip_path.exists() and prev.get("etag"):
        headers["If-None-Match"] = prev["etag"]
    elif not force and zip_path.exists() and prev.get("last_modified"):
        headers["If-Modified-Since"] = prev["last_modified"]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120) as client:
        got = _download(client, city["gtfs_url"], zip_path, headers)
    if got is None:
        return "CTA feed unchanged"
    meta = gtfs.write(zip_path, cta_dir)
    record("cta_gtfs", etag=got.get("etag"), last_modified=got.get("last-modified"),
           credit=city["gtfs_credit"], **meta)
    return f"CTA feed imported: {meta['counts']}, valid to {meta['valid_to']}"


def import_gtfs(city: dict) -> str:
    """Rebuild the overlays from the zip already in the cache."""
    cta_dir = config.cache_dir() / "cta"
    meta = gtfs.write(cta_dir / "google_transit.zip", cta_dir)
    prev = read_versions().get("cta_gtfs", {})
    record("cta_gtfs", etag=prev.get("etag"), last_modified=prev.get("last_modified"),
           credit=city["gtfs_credit"], **meta)
    return f"CTA overlays rebuilt: {meta['counts']}, valid to {meta['valid_to']}"


def _pmtiles_cli() -> str:
    """The `pmtiles` command line tool (github.com/protomaps/go-pmtiles).

    Not downloaded by the app: a binary fetched and run without a checksum is
    not something to automate. The host installs it (the stack's tools image).
    """
    found = shutil.which("pmtiles")
    if not found:
        raise RuntimeError("the `pmtiles` tool is not on PATH; install go-pmtiles (see data/README.md)")
    return found


def latest_protomaps_build(city: dict, today: date | None = None) -> str:
    """URL of the newest daily Protomaps planet build (tries the last 10 days)."""
    today = today or date.today()
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30) as client:
        for back in range(1, 11):
            url = f"{city['protomaps_builds']}{(today - timedelta(days=back)):%Y%m%d}.pmtiles"
            if client.head(url, follow_redirects=True).status_code == 200:
                return url
    raise RuntimeError("no Protomaps build found in the last 10 days")


def extract_command(cli: str, source: str, dest: Path, bbox: list[float]) -> list[str]:
    return [cli, "extract", source, str(dest), "--bbox=" + ",".join(str(v) for v in bbox)]


def build_tiles(city: dict) -> str:
    """Cut the city's region out of the public Protomaps build (OSM, ODbL)."""
    dest = config.cache_dir() / "tiles" / "city.pmtiles"
    dest.parent.mkdir(parents=True, exist_ok=True)
    source = latest_protomaps_build(city)
    tmp = dest.with_suffix(".part")
    subprocess.run(extract_command(_pmtiles_cli(), source, tmp, city["bbox"]), check=True)
    tmp.replace(dest)
    record("tiles", source=source, bbox=city["bbox"], bytes=dest.stat().st_size,
           credit="© OpenStreetMap contributors, Protomaps")
    return f"tiles built from {source}: {dest.stat().st_size} bytes"


def fetch_assets(city: dict) -> str:
    """Fonts and sprites for the basemap style, served from the app itself."""
    url = f"https://github.com/protomaps/basemaps-assets/archive/{city['assets_ref']}.tar.gz"
    dest = config.cache_dir() / "basemap-assets"
    with tempfile.TemporaryDirectory() as tmp:
        archive = Path(tmp) / "assets.tar.gz"
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=300) as client:
            _download(client, url, archive)
        with tarfile.open(archive) as tar:
            members = [m for m in tar.getmembers() if "/fonts/" in m.name or "/sprites/v4/" in m.name]
            tar.extractall(tmp, members=members, filter="data")
        root = next(Path(tmp).glob("basemaps-assets-*"))
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        shutil.move(str(root / "fonts"), dest / "fonts")
        shutil.move(str(root / "sprites"), dest / "sprites")
    record("basemap_assets", ref=city["assets_ref"])
    return "basemap fonts and sprites fetched"


def fetch_osm(city: dict, force: bool = False) -> str:
    """Download the regional OSM extract (conditional on its ETag)."""
    pbf = config.cache_dir() / "osm" / "extract.osm.pbf"
    prev = read_versions().get("osm_extract", {})
    headers = {}
    if not force and pbf.exists() and prev.get("etag"):
        headers["If-None-Match"] = prev["etag"]
    elif not force and pbf.exists() and prev.get("last_modified"):
        headers["If-Modified-Since"] = prev["last_modified"]
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=600) as client:
        got = _download(client, city["osm_extract_url"], pbf, headers)
    if got is None:
        return "OSM extract unchanged"
    record("osm_extract", etag=got.get("etag"), last_modified=got.get("last-modified"),
           url=city["osm_extract_url"], credit="© OpenStreetMap contributors (ODbL)")
    return f"OSM extract fetched: {pbf.stat().st_size} bytes"


def fetch_pools(city: dict) -> str:
    """Download the Chicago Park District facility list (public domain)."""
    dest = config.cache_dir() / "places" / "park_district.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120) as client:
        resp = client.get(city["pools_url"], params={"$where": "facility_name like '%POOL%'", "$limit": "500"})
        resp.raise_for_status()
    dest.write_bytes(resp.content)
    record("park_district_pools", url=city["pools_url"], rows=len(resp.json()),
           credit="Chicago Park District (City of Chicago data portal, public domain; 2016 list)")
    return f"Park District facilities fetched: {len(resp.json())} rows"


def import_places(city: dict) -> str:
    """Import OSM places, the Park District pools and the CTA stops into the database."""
    conn = db.connect()
    lines = []
    pbf = config.cache_dir() / "osm" / "extract.osm.pbf"
    if pbf.exists():
        lines.append(f"osm: {importer.import_osm(conn, pbf, city['bbox'])}")
    else:
        lines.append("osm: no extract in the cache (run fetch-osm); skipped")
    pools = config.cache_dir() / "places" / "park_district.json"
    if pools.exists():
        lines.append(f"park district: {importer.import_pools(conn, json.loads(pools.read_text(encoding='utf-8')))}")
    else:
        lines.append("park district: not fetched (run fetch-pools); skipped")
    if (config.cache_dir() / "cta" / "stops.geojson").exists():
        lines.append(f"cta stops: {importer.import_cta_stops(conn)}")
    return "\n".join(lines)


def status() -> dict:
    versions = read_versions()
    cta = versions.get("cta_gtfs")
    if cta:
        cta["status"] = feed_status(cta.get("valid_to"))
    return versions


def main(argv: list[str]) -> int:
    commands = {
        "fetch-gtfs": lambda c: fetch_gtfs(c),
        "import-gtfs": import_gtfs,
        "build-tiles": build_tiles,
        "fetch-assets": fetch_assets,
        "fetch-osm": fetch_osm,
        "fetch-pools": fetch_pools,
        "import-places": import_places,
    }
    if len(argv) != 1 or argv[0] not in (*commands, "status"):
        print("usage: python -m aptscout <" + "|".join((*commands, "status")) + ">", file=sys.stderr)
        return 2
    if argv[0] == "status":
        print(json.dumps(status(), indent=2, sort_keys=True))
        return 0
    print(commands[argv[0]](config.load_city()))
    return 0
