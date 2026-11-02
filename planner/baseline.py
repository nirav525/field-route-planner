"""A simple comparison plan: each technician in turn always drives to the nearest stop that fits.

It respects the same hours and assignments as the solver, so the two plans are comparable,
but it has no sense of which sites matter most, so it can drop a must-visit or urgent site.
"""
from __future__ import annotations

from .models import Plan, Route, Stop, drive_minutes, miles_between
from .problem import Problem


def nearest_neighbor(problem: Problem) -> Plan:
    remaining = list(problem.sites)
    routes = []

    for tech in problem.techs:
        route = Route(tech.id)
        x, y, now = tech.x, tech.y, tech.shift_start
        while True:
            best, best_miles = None, None
            for site in remaining:
                if problem.allowed_tech.get(site.id, tech.id) != tech.id:
                    continue
                miles = miles_between(x, y, site.x, site.y)
                arrive = max(now + drive_minutes(miles), site.open_min)
                leave = arrive + site.service_min
                home = leave + drive_minutes(miles_between(site.x, site.y, tech.x, tech.y))
                if leave > site.close_min or home > tech.shift_end:
                    continue
                if best is None or miles < best_miles:
                    best, best_miles = site, miles
            if best is None:
                break
            arrive = max(now + drive_minutes(best_miles), best.open_min)
            route.stops.append(Stop(best.id, arrive, arrive + best.service_min))
            route.miles += best_miles
            route.drive_min += drive_minutes(best_miles)
            x, y, now = best.x, best.y, arrive + best.service_min
            remaining.remove(best)
        if route.stops:
            miles = miles_between(x, y, tech.x, tech.y)
            route.miles += miles
            route.drive_min += drive_minutes(miles)
            route.finish = now + drive_minutes(miles)
        routes.append(route)

    return Plan(routes, [s.id for s in remaining])
