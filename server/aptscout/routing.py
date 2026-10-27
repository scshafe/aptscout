"""Travel time between an origin and places (design section 4).

`StraightLine` is the always-available estimate (distance x detour at walking
speed). `Valhalla` asks a self-hosted Valhalla for the street network walk.
"""

import math
import os
from typing import Protocol

import httpx

WALK_KMH = float(os.environ.get("APTSCOUT_WALK_KMH", "4.8"))
DETOUR = 1.3  # street network vs straight line, used when no router is configured
BIKE_KMH = float(os.environ.get("APTSCOUT_BIKE_KMH", "15"))
DRIVE_KMH = float(os.environ.get("APTSCOUT_DRIVE_KMH", "28"))  # city average, free flow, parking not included
MODES = ("walk", "bike", "drive")
Point = tuple[float, float]  # (lat, lon)


def haversine_m(a: Point, b: Point) -> float:
    dx = math.radians(b[1] - a[1]) * math.cos(math.radians((a[0] + b[0]) / 2))
    dy = math.radians(b[0] - a[0])
    return 6371000.0 * math.hypot(dx, dy)


def walk_minutes(metres: float) -> float:
    return metres / (WALK_KMH * 1000 / 60)


class Router(Protocol):
    name: str

    def walk_minutes(self, origin: Point, targets: list[Point], measure: str) -> list[float | None]:
        """Walking minutes to each target under `measure`; None when unreachable."""

    def travel_minutes(self, origin: Point, targets: list[Point], mode: str) -> list[float | None]:
        """Minutes by walk, bike or drive to each target; None when unreachable."""


def speed_kmh(mode: str) -> float:
    return {"walk": WALK_KMH, "bike": BIKE_KMH, "drive": DRIVE_KMH}[mode]


class StraightLine:
    name = "straight"

    def travel_minutes(self, origin, targets, mode):
        return [haversine_m(origin, t) * DETOUR / (speed_kmh(mode) * 1000 / 60) for t in targets]

    def walk_minutes(self, origin, targets, measure):
        factor = 1.0 if measure == "straight" else DETOUR
        return [walk_minutes(haversine_m(origin, t) * factor) for t in targets]


class Valhalla:
    name = "valhalla"

    def __init__(self, url: str, client: httpx.Client | None = None):
        self.url = url.rstrip("/")
        self.client = client or httpx.Client(timeout=30)

    def walk_minutes(self, origin, targets, measure):
        if measure == "straight":
            return StraightLine().walk_minutes(origin, targets, measure)
        body = {
            "sources": [{"lat": origin[0], "lon": origin[1]}],
            "targets": [{"lat": t[0], "lon": t[1]} for t in targets],
            "costing": "pedestrian",
            "costing_options": {"pedestrian": {"walking_speed": WALK_KMH}},
        }
        resp = self.client.post(self.url + "/sources_to_targets", json=body)
        resp.raise_for_status()
        cells = resp.json()["sources_to_targets"][0]
        out: list[float | None] = [None] * len(targets)
        for cell in cells:
            if cell.get("time") is None:
                continue
            # walk_distance: network metres at the configured speed; walk_time: Valhalla's time
            out[cell["to_index"]] = (
                walk_minutes(cell["distance"] * 1000) if measure == "walk_distance" else cell["time"] / 60
            )
        return out


    def travel_minutes(self, origin, targets, mode):
        if mode == "walk":
            return self.walk_minutes(origin, targets, "walk_time")
        costing = {"bike": "bicycle", "drive": "auto"}[mode]
        body = {
            "sources": [{"lat": origin[0], "lon": origin[1]}],
            "targets": [{"lat": t[0], "lon": t[1]} for t in targets],
            "costing": costing,
        }
        resp = self.client.post(self.url + "/sources_to_targets", json=body)
        resp.raise_for_status()
        out: list[float | None] = [None] * len(targets)
        for cell in resp.json()["sources_to_targets"][0]:
            if cell.get("time") is not None:
                out[cell["to_index"]] = cell["time"] / 60
        return out


def make_router() -> Router:
    url = os.environ.get("APTSCOUT_VALHALLA_URL")
    return Valhalla(url) if url else StraightLine()
