"""Turns sites, technicians and rules into the one problem both planners solve."""
from __future__ import annotations

from dataclasses import dataclass

from .models import DUE_BELOW_STOCK_PCT, Rule, Site, Technician, to_minutes


@dataclass
class Problem:
    sites: list[Site]  # only the sites due today
    techs: list[Technician]  # only the technicians working today, with adjusted shifts
    allowed_tech: dict[str, str]  # site id -> the one tech allowed to serve it
    must_visit: set[str]


def build_problem(sites: list[Site], techs: list[Technician], rules: list[Rule]) -> Problem:
    skip = {r.site for r in rules if r.type == "site_skip"}
    must = {r.site for r in rules if r.type == "site_must_visit"}
    out = {r.tech for r in rules if r.type == "tech_unavailable"}
    allowed = {r.site: r.tech for r in rules if r.type == "site_assign"}

    windows = {r.site: (to_minutes(r.start), to_minutes(r.end)) for r in rules if r.type == "site_window"}
    starts = {r.tech: to_minutes(r.start) for r in rules if r.type == "tech_start_after"}
    ends = {r.tech: to_minutes(r.end) for r in rules if r.type == "tech_end_by"}

    due = []
    for s in sites:
        if s.id in skip or not (s.stock_pct < DUE_BELOW_STOCK_PCT or s.id in must):
            continue
        open_min, close_min = s.open_min, s.close_min
        if s.id in windows:
            open_min, close_min = max(open_min, windows[s.id][0]), min(close_min, windows[s.id][1])
        due.append(Site(s.id, s.x, s.y, s.stock_pct, open_min, close_min, s.service_min))

    working = []
    for t in techs:
        if t.id in out:
            continue
        start, end = max(t.shift_start, starts.get(t.id, 0)), min(t.shift_end, ends.get(t.id, 24 * 60))
        if start < end:
            working.append(Technician(t.id, t.x, t.y, start, end))

    return Problem(due, working, allowed, must)


def check_plan(plan, problem: Problem) -> list[str]:
    """Recomputes a plan from scratch and lists every broken constraint.

    The app runs this on every plan before showing it, so a solver or baseline bug
    shows up as a visible error instead of a bad route.
    """
    from .models import drive_minutes, miles_between

    problems = []
    sites = {s.id: s for s in problem.sites}
    techs = {t.id: t for t in problem.techs}
    seen = []

    for route in plan.routes:
        tech = techs.get(route.tech)
        if tech is None:
            if route.stops:
                problems.append(f"Tech {route.tech} is not working today but has stops")
            continue
        x, y, clock = tech.x, tech.y, tech.shift_start
        for stop in route.stops:
            site = sites.get(stop.site)
            if site is None:
                problems.append(f"{stop.site} is on a route but was not due")
                continue
            seen.append(stop.site)
            earliest = clock + drive_minutes(miles_between(x, y, site.x, site.y))
            if stop.arrive < earliest:
                problems.append(f"{stop.site}: arrival is before the drive could finish")
            if stop.arrive < site.open_min or stop.arrive + site.service_min > site.close_min:
                problems.append(f"{stop.site}: visit falls outside its hours")
            if problem.allowed_tech.get(stop.site, route.tech) != route.tech:
                problems.append(f"{stop.site}: assigned to the wrong tech")
            x, y, clock = site.x, site.y, stop.arrive + site.service_min
        if route.stops:
            back = clock + drive_minutes(miles_between(x, y, tech.x, tech.y))
            if back > tech.shift_end:
                problems.append(f"Tech {route.tech} gets home after the shift ends")

    if len(seen) != len(set(seen)):
        problems.append("A site appears on more than one route")
    missing = set(sites) - set(seen) - set(plan.dropped)
    if missing:
        problems.append(f"Not on a route and not listed as dropped: {sorted(missing)}")
    return problems
