"""Records what happened to each plan, so the tool can report whether it is working."""
from __future__ import annotations

import csv
import statistics
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .models import Plan

LOG_PATH = Path(__file__).resolve().parent.parent / "data" / "decisions.csv"


@dataclass
class Decision:
    approved_at: str
    stops: int
    dropped: int
    miles: float
    baseline_miles: float
    solve_seconds: float
    review_seconds: float
    changes_made: int


def compare(plan: Plan, baseline: Plan) -> dict:
    """Miles per stop keeps the comparison fair when the two plans serve different numbers of stops."""
    def per_stop(p: Plan) -> float:
        return p.miles / p.stops if p.stops else 0.0

    return {
        "stops": (plan.stops, baseline.stops),
        "dropped": (len(plan.dropped), len(baseline.dropped)),
        "miles": (plan.miles, baseline.miles),
        "drive_min": (plan.drive_min, baseline.drive_min),
        "miles_per_stop": (per_stop(plan), per_stop(baseline)),
    }


def log_decision(plan: Plan, baseline: Plan, review_seconds: float, changes_made: int, path: Path = LOG_PATH) -> Decision:
    decision = Decision(
        approved_at=datetime.now().isoformat(timespec="seconds"),
        stops=plan.stops,
        dropped=len(plan.dropped),
        miles=round(plan.miles, 1),
        baseline_miles=round(baseline.miles, 1),
        solve_seconds=round(plan.solve_seconds, 2),
        review_seconds=round(review_seconds, 1),
        changes_made=changes_made,
    )
    is_new = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=Decision.__dataclass_fields__.keys())
        if is_new:
            writer.writeheader()
        writer.writerow(asdict(decision))
    return decision


def summarize(path: Path = LOG_PATH) -> dict | None:
    """Across approved plans: how often people accept as is, and how long a plan takes end to end."""
    if not path.exists():
        return None
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    unchanged = sum(1 for r in rows if int(r["changes_made"]) == 0)
    return {
        "plans": len(rows),
        "accepted_unchanged_pct": round(100 * unchanged / len(rows)),
        "median_minutes_to_approve": round(
            statistics.median((float(r["solve_seconds"]) + float(r["review_seconds"])) / 60 for r in rows), 1
        ),
    }
