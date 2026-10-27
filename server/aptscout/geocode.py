"""Geocoding through a self-hosted Nominatim (design section 3.5).

Never a public geocoder: an address typed here is the owner's private data.
With no APTSCOUT_NOMINATIM_URL the app still works; the owner drops the pin.
"""

import os

import httpx

USER_AGENT = "aptscout/0.1 (self-hosted)"


class NotConfigured(Exception):
    pass


def base_url() -> str | None:
    return os.environ.get("APTSCOUT_NOMINATIM_URL") or None


def parse(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        try:
            out.append({"label": r["display_name"], "lat": float(r["lat"]), "lon": float(r["lon"])})
        except (KeyError, ValueError, TypeError):
            continue
    return out


def search(query: str, bbox: list[float] | None = None, client: httpx.Client | None = None) -> list[dict]:
    """Candidates for an address, best first. bbox biases toward the city."""
    url = base_url()
    if url is None:
        raise NotConfigured()
    params = {"q": query, "format": "jsonv2", "limit": "5", "countrycodes": "us"}
    if bbox:
        params["viewbox"] = ",".join(str(v) for v in (bbox[0], bbox[3], bbox[2], bbox[1]))
    own = client or httpx.Client(timeout=15, headers={"User-Agent": USER_AGENT})
    try:
        resp = own.get(url.rstrip("/") + "/search", params=params)
        resp.raise_for_status()
        return parse(resp.json())
    finally:
        if client is None:
            own.close()
