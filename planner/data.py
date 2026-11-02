"""Generates and loads the made-up sites and technicians. No real places or people."""
from __future__ import annotations

import csv
import random
from pathlib import Path

from .models import Site, Technician

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# (id, shift start, shift end) in minutes after midnight
SHIFTS = [("A", 7 * 60, 15 * 60), ("B", 8 * 60, 16 * 60), ("C", 9 * 60, 17 * 60), ("D", 11 * 60, 19 * 60)]


def generate(seed: int = 7, n_sites: int = 40) -> tuple[list[Site], list[Technician]]:
    """Sites sit in loose clusters on a 50 by 40 mile map, the way real service areas do."""
    rng = random.Random(seed)
    centers = [(rng.uniform(5, 45), rng.uniform(5, 35)) for _ in range(5)]

    sites = []
    for i in range(1, n_sites + 1):
        cx, cy = rng.choice(centers)
        sites.append(
            Site(
                id=f"S{i:02d}",
                x=round(min(50, max(0, rng.gauss(cx, 4))), 1),
                y=round(min(40, max(0, rng.gauss(cy, 4))), 1),
                stock_pct=rng.randint(5, 100),
                open_min=rng.choice([7, 8, 8, 9, 10]) * 60,
                close_min=rng.choice([15, 16, 17, 18, 18, 20]) * 60,
                service_min=rng.choice([30, 35, 40, 45, 50]),
            )
        )

    techs = [
        Technician(id=tid, x=round(rng.uniform(10, 40), 1), y=round(rng.uniform(8, 32), 1), shift_start=start, shift_end=end)
        for tid, start, end in SHIFTS
    ]
    return sites, techs


def save(sites: list[Site], techs: list[Technician], folder: Path = DATA_DIR) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    for name, rows in (("sites.csv", sites), ("technicians.csv", techs)):
        with open(folder / name, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=rows[0].__dataclass_fields__.keys())
            writer.writeheader()
            writer.writerows(vars(r) for r in rows)


def load(folder: Path = DATA_DIR) -> tuple[list[Site], list[Technician]]:
    with open(folder / "sites.csv", newline="") as f:
        sites = [
            Site(r["id"], float(r["x"]), float(r["y"]), int(r["stock_pct"]), int(r["open_min"]), int(r["close_min"]), int(r["service_min"]))
            for r in csv.DictReader(f)
        ]
    with open(folder / "technicians.csv", newline="") as f:
        techs = [
            Technician(r["id"], float(r["x"]), float(r["y"]), int(r["shift_start"]), int(r["shift_end"]))
            for r in csv.DictReader(f)
        ]
    return sites, techs


if __name__ == "__main__":
    save(*generate())
    print(f"Wrote sites.csv and technicians.csv to {DATA_DIR}")
