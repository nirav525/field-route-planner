"""Plain data types shared by the solver, the baseline and the app.

Times are minutes after midnight. Positions are miles on a made-up map.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot

ROAD_FACTOR = 1.3  # straight-line miles to rough road miles
AVG_MPH = 30
DUE_BELOW_STOCK_PCT = 60  # a site needs a visit when stock is under this
URGENT_BELOW_STOCK_PCT = 20  # an urgent site should almost never be dropped

RULE_TYPES = {
    "tech_unavailable": {"tech"},
    "tech_start_after": {"tech", "start"},
    "tech_end_by": {"tech", "end"},
    "site_skip": {"site"},
    "site_must_visit": {"site"},
    "site_assign": {"site", "tech"},
    "site_window": {"site", "start", "end"},
}


@dataclass(frozen=True)
class Site:
    id: str
    x: float
    y: float
    stock_pct: int
    open_min: int
    close_min: int
    service_min: int


@dataclass(frozen=True)
class Technician:
    id: str
    x: float
    y: float
    shift_start: int
    shift_end: int


@dataclass(frozen=True)
class Rule:
    type: str
    tech: str | None = None
    site: str | None = None
    start: str | None = None
    end: str | None = None
    source: str = ""  # the words this rule came from, shown to the reviewer

    def describe(self) -> str:
        return {
            "tech_unavailable": f"Tech {self.tech} is out today",
            "tech_start_after": f"Tech {self.tech} starts no earlier than {self.start}",
            "tech_end_by": f"Tech {self.tech} finishes by {self.end}",
            "site_skip": f"Skip {self.site} today",
            "site_must_visit": f"{self.site} must be visited today",
            "site_assign": f"{self.site} goes to Tech {self.tech}",
            "site_window": f"{self.site} only between {self.start} and {self.end}",
        }.get(self.type, self.type)


@dataclass
class Stop:
    site: str
    arrive: int
    depart: int


@dataclass
class Route:
    tech: str
    stops: list[Stop] = field(default_factory=list)
    miles: float = 0.0
    drive_min: int = 0
    finish: int | None = None


@dataclass
class Plan:
    routes: list[Route]
    dropped: list[str]
    solve_seconds: float = 0.0

    @property
    def stops(self) -> int:
        return sum(len(r.stops) for r in self.routes)

    @property
    def miles(self) -> float:
        return sum(r.miles for r in self.routes)

    @property
    def drive_min(self) -> int:
        return sum(r.drive_min for r in self.routes)


def miles_between(ax: float, ay: float, bx: float, by: float) -> float:
    return hypot(ax - bx, ay - by) * ROAD_FACTOR


def drive_minutes(miles: float) -> int:
    return round(miles / AVG_MPH * 60)


def to_minutes(hhmm: str) -> int:
    hours, minutes = hhmm.split(":")
    return int(hours) * 60 + int(minutes)


def to_hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"
