"""Schedule-based CTA travel times from a self-hosted OpenTripPlanner 2 (design 4.2, 4.4).

The best itinerary at a few departures inside a time band, on a real service
date inside the CTA feed's validity; the median duration is the band's time.
Uses OTP's GTFS GraphQL API (`/otp/gtfs/v1`).
"""

import os
import statistics
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from . import datasets

# Departure times per band; the rush is the morning going out and the evening coming back.
DEPARTURES = {
    ("weekday_rush", "out"): ("07:30", "08:00", "08:30"),
    ("weekday_rush", "back"): ("17:00", "17:30", "18:00"),
    ("weekday_midday", "out"): ("11:00", "12:00", "13:00"),
    ("weekday_midday", "back"): ("11:00", "12:00", "13:00"),
    ("evening", "out"): ("19:00", "20:00", "21:00"),
    ("evening", "back"): ("19:00", "20:00", "21:00"),
    ("saturday", "out"): ("10:00", "12:00", "14:00"),
    ("saturday", "back"): ("10:00", "12:00", "14:00"),
    ("sunday", "out"): ("10:00", "12:00", "14:00"),
    ("sunday", "back"): ("10:00", "12:00", "14:00"),
}
WEEKDAY = {"weekday_rush": 2, "weekday_midday": 2, "evening": 2, "saturday": 5, "sunday": 6}  # Wednesday, Sat, Sun

# OTP 2.7 and later: planConnection (plan is deprecated there). Older 2.x: plan.
CONNECTION_QUERY = """
query Plan($dateTime: OffsetDateTime!, $from: Float!, $fromLon: Float!, $to: Float!, $toLon: Float!) {
  planConnection(
    origin: {location: {coordinate: {latitude: $from, longitude: $fromLon}}}
    destination: {location: {coordinate: {latitude: $to, longitude: $toLon}}}
    dateTime: {earliestDeparture: $dateTime}
    first: 3
  ) { edges { node { duration } } }
}
"""
LEGACY_QUERY = """
query Plan($date: String!, $time: String!, $from: InputCoordinates!, $to: InputCoordinates!) {
  plan(date: $date, time: $time, from: $from, to: $to, arriveBy: false, numItineraries: 3,
       transportModes: [{mode: TRANSIT}, {mode: WALK}]) {
    itineraries { duration }
  }
}
"""
TIMEZONE = ZoneInfo("America/Chicago")


class NoRoute(Exception):
    pass


def service_date(band: str, today: date, valid_to: date | None) -> date:
    """The next day of the band's kind, stepped back a week at a time to stay inside the feed."""
    target = WEEKDAY[band]
    day = today + timedelta(days=(target - today.weekday()) % 7)
    if valid_to is not None:
        while day > valid_to:
            day -= timedelta(days=7)
    return day


class Otp:
    name = "otp"

    def __init__(self, url: str, client: httpx.Client | None = None, valid_to: date | None = None,
                 today: date | None = None):
        self.url = url.rstrip("/")
        self.client = client or httpx.Client(timeout=60)
        self._valid_to = valid_to  # tests; otherwise read from the imported feed
        self.today = today
        self.modern = True

    def valid_to(self) -> date | None:
        if self._valid_to is not None:
            return self._valid_to
        text = datasets.read_versions().get("cta_gtfs", {}).get("valid_to")
        return date.fromisoformat(text) if text else None

    def _post(self, query: str, variables: dict) -> dict:
        resp = self.client.post(self.url + "/otp/gtfs/v1", json={"query": query, "variables": variables})
        resp.raise_for_status()
        return resp.json()

    def _duration(self, day: date, time: str, origin, dest) -> float | None:
        """Minutes of the quickest itinerary leaving at `time` (hh:mm) on `day`, or None."""
        if self.modern:
            stamp = datetime.fromisoformat(f"{day.isoformat()}T{time}:00").replace(tzinfo=TIMEZONE).isoformat()
            data = self._post(CONNECTION_QUERY, {"dateTime": stamp, "from": origin[0], "fromLon": origin[1],
                                                 "to": dest[0], "toLon": dest[1]})
            if self._unknown_field(data, "planConnection"):
                self.modern = False  # an older OTP: remember and use plan
                return self._duration(day, time, origin, dest)
            nodes = [e["node"] for e in (((data.get("data") or {}).get("planConnection") or {}).get("edges") or [])]
        else:
            data = self._post(LEGACY_QUERY, {"date": day.isoformat(), "time": time + ":00",
                                             "from": {"lat": origin[0], "lon": origin[1]}, "to": {"lat": dest[0], "lon": dest[1]}})
            nodes = ((data.get("data") or {}).get("plan") or {}).get("itineraries") or []
        if data.get("errors"):
            raise NoRoute(str(data["errors"][0].get("message", "OTP error"))[:120])
        durations = [n["duration"] for n in nodes if n.get("duration") is not None]
        return min(durations) / 60 if durations else None

    @staticmethod
    def _unknown_field(data: dict, field: str) -> bool:
        return any(field in str(e.get("message", "")) and ("undefined" in str(e).lower() or "validation" in str(e).lower())
                   for e in data.get("errors") or [])

    def minutes(self, origin, dest, band: str, direction: str) -> tuple[float, str]:
        """The median best-itinerary minutes over the band's departures."""
        day = service_date(band, self.today or datetime.now().date(), self.valid_to())
        times = [self._duration(day, t, origin, dest) for t in DEPARTURES[(band, direction)]]
        found = [t for t in times if t is not None]
        if not found:
            raise NoRoute("no itinerary")
        return statistics.median(found), "otp"


def make_engine() -> Otp | None:
    url = os.environ.get("APTSCOUT_OTP_URL")
    return Otp(url) if url else None
