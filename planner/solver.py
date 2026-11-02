"""Routes technicians with OR-Tools.

Routing is a solver's job, not an LLM's: the answer has to respect hard limits every
time, and running it costs nothing per call.
"""
from __future__ import annotations

import time

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .models import URGENT_BELOW_STOCK_PCT, DUE_BELOW_STOCK_PCT, Plan, Route, Stop, drive_minutes, miles_between
from .problem import Problem

MUST_VISIT_PENALTY = 1_000_000
URGENT_PENALTY = 20_000


def drop_penalty(stock_pct: int, must_visit: bool) -> int:
    """What dropping a site costs, in drive minutes. Emptier sites cost more to skip."""
    if must_visit:
        return MUST_VISIT_PENALTY
    if stock_pct < URGENT_BELOW_STOCK_PCT:
        return URGENT_PENALTY
    return 200 + (DUE_BELOW_STOCK_PCT - stock_pct) * 20


def solve(problem: Problem, time_limit_s: int = 3) -> Plan:
    started = time.perf_counter()
    sites, techs = problem.sites, problem.techs
    if not techs:
        return Plan([], [s.id for s in sites], time.perf_counter() - started)

    # Nodes: one home per technician, then the sites.
    points = [(t.x, t.y) for t in techs] + [(s.x, s.y) for s in sites]
    service = [0] * len(techs) + [s.service_min for s in sites]
    n_techs = len(techs)
    homes = list(range(n_techs))

    manager = pywrapcp.RoutingIndexManager(len(points), n_techs, homes, homes)
    routing = pywrapcp.RoutingModel(manager)

    def drive(a: int, b: int) -> int:
        return drive_minutes(miles_between(*points[a], *points[b]))

    def drive_cb(i: int, j: int) -> int:
        return drive(manager.IndexToNode(i), manager.IndexToNode(j))

    def elapsed_cb(i: int, j: int) -> int:
        a, b = manager.IndexToNode(i), manager.IndexToNode(j)
        return service[a] + drive(a, b)

    routing.SetArcCostEvaluatorOfAllVehicles(routing.RegisterTransitCallback(drive_cb))

    routing.AddDimension(routing.RegisterTransitCallback(elapsed_cb), 24 * 60, 24 * 60, False, "time")
    clock = routing.GetDimensionOrDie("time")

    for v, tech in enumerate(techs):
        clock.CumulVar(routing.Start(v)).SetRange(tech.shift_start, tech.shift_end)
        clock.CumulVar(routing.End(v)).SetRange(tech.shift_start, tech.shift_end)
        routing.AddVariableMinimizedByFinalizer(clock.CumulVar(routing.End(v)))
        routing.AddVariableMaximizedByFinalizer(clock.CumulVar(routing.Start(v)))

    tech_index = {t.id: v for v, t in enumerate(techs)}
    for k, site in enumerate(sites):
        index = manager.NodeToIndex(n_techs + k)
        latest_arrival = site.close_min - site.service_min
        if latest_arrival < site.open_min:
            # The visit can't fit in the window, so the site can only be dropped.
            routing.AddDisjunction([index], drop_penalty(site.stock_pct, site.id in problem.must_visit))
            routing.VehicleVar(index).SetValues([-1])
            continue
        clock.CumulVar(index).SetRange(site.open_min, latest_arrival)
        routing.AddDisjunction([index], drop_penalty(site.stock_pct, site.id in problem.must_visit))
        assigned = problem.allowed_tech.get(site.id)
        if assigned is not None:
            if assigned in tech_index:
                routing.VehicleVar(index).SetValues([-1, tech_index[assigned]])
            else:
                routing.VehicleVar(index).SetValues([-1])

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    params.time_limit.seconds = time_limit_s

    solution = routing.SolveWithParameters(params)
    if solution is None:
        return Plan([], [s.id for s in sites], time.perf_counter() - started)

    routes, visited = [], set()
    for v, tech in enumerate(techs):
        index = routing.Start(v)
        route = Route(tech.id)
        x, y, now = tech.x, tech.y, solution.Min(clock.CumulVar(index))
        while True:
            index = solution.Value(routing.NextVar(index))
            if routing.IsEnd(index):
                break
            site = sites[manager.IndexToNode(index) - n_techs]
            miles = miles_between(x, y, site.x, site.y)
            arrive = max(now + drive_minutes(miles), site.open_min)
            route.stops.append(Stop(site.id, arrive, arrive + site.service_min))
            route.miles += miles
            route.drive_min += drive_minutes(miles)
            visited.add(site.id)
            x, y, now = site.x, site.y, arrive + site.service_min
        if route.stops:
            miles = miles_between(x, y, tech.x, tech.y)
            route.miles += miles
            route.drive_min += drive_minutes(miles)
            route.finish = now + drive_minutes(miles)
        routes.append(route)

    dropped = [s.id for s in sites if s.id not in visited]
    return Plan(routes, dropped, time.perf_counter() - started)
