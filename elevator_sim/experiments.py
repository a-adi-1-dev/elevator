"""Reproducible experiments: compare schedulers across traffic patterns, fleet sizes,
door times and the seat-reservation fairness policy.

    python -m elevator_sim.experiments            # full run (a few minutes), writes results/
    python -m elevator_sim.experiments --quick    # fewer seeds, for a smoke test

Every number is averaged over several random seeds, because a single generated
file can make one scheduler look better or worse by luck.

Outputs (in --out, default results/):
    runs.csv      one row per simulation run
    summary.md    the aggregated tables
    *.png         charts (needs matplotlib; skipped with a note if it is missing)
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import SimulationConfig
from .generators import generate_normal, generate_random
from .schedulers import make_scheduler
from .simulation import Simulation

# The base building: a mid-rise office tower.
FLOORS = 20
ELEVATORS = 4
CAPACITY = 10
TICKS = 600  # requests arrive over this many ticks

# (share of trips from the lobby, share to the lobby); the rest are between upper floors.
TRAFFIC = {
    "up-peak": (0.85, 0.05),     # morning arrivals
    "down-peak": (0.05, 0.85),   # evening departures
    "mixed": (0.40, 0.40),       # a normal day
    "random": None,              # every pair of floors equally likely
}
SCHEDULER_ORDER = ["naive", "nearest-car", "zone", "least-cost"]


@dataclass(frozen=True)
class Case:
    experiment: str
    traffic: str
    scheduler: str
    reserve_seats: bool
    door_time: int
    elevators: int
    passengers: int
    seed: int
    floors: int = FLOORS
    capacity: int = CAPACITY


def run_case(case: Case) -> dict:
    if TRAFFIC[case.traffic] is None:
        passengers = generate_random(case.passengers, TICKS, case.floors, seed=case.seed)
    else:
        up, down = TRAFFIC[case.traffic]
        passengers = generate_normal(case.passengers, TICKS, case.floors, up, down, seed=case.seed)
    config = SimulationConfig(case.elevators, case.floors, case.capacity, door_time=case.door_time)
    result = Simulation(config, passengers, make_scheduler(case.scheduler, case.reserve_seats)).run()
    wait, total = result.wait_stats, result.total_stats
    return {
        **asdict(case),
        "ticks": result.ticks,
        "completed": len(result.completed),
        "wait_avg": wait.mean, "wait_p95": wait.p95, "wait_max": wait.max,
        "total_avg": total.mean, "total_p95": total.p95, "total_max": total.max,
        "floors_moved": sum(e.floors_travelled for e in result.elevators),
        "transfers": sum(j.transfers for j in result.journeys),
    }


def plan(seeds: int) -> list[Case]:
    cases: list[Case] = []
    # 1. Every scheduler on every traffic pattern, with free stops (the brief) and 2-tick doors.
    for traffic in TRAFFIC:
        for scheduler in SCHEDULER_ORDER:
            for door_time in (0, 2):
                for seed in range(seeds):
                    cases.append(Case("schedulers", traffic, scheduler, False, door_time, ELEVATORS, 600, seed))
    # 2. Fleet size: how many cars does the building need?
    for elevators in range(1, 11):
        for scheduler in ("nearest-car", "least-cost"):
            for seed in range(seeds):
                cases.append(Case("fleet", "mixed", scheduler, False, 0, elevators, 600, seed))
    # 3. Door time: when do zones pay off? (lobby-heavy traffic, taller building)
    for door_time in (0, 1, 2, 3, 4):
        for scheduler in ("nearest-car", "zone", "least-cost"):
            for seed in range(seeds):
                cases.append(Case("door-time", "up-peak", scheduler, False, door_time, ELEVATORS, 300, seed,
                                  floors=40))
    # 4. Fairness vs efficiency: seat reservation on/off as load rises.
    for passengers in (300, 600, 900, 1200):
        for scheduler in ("nearest-car", "least-cost"):
            for reserve in (False, True):
                for seed in range(seeds):
                    cases.append(Case("fairness", "mixed", scheduler, reserve, 0, ELEVATORS, passengers, seed,
                                      capacity=4))
    return cases


def aggregate(rows: list[dict], keys: list[str]) -> list[dict]:
    """Average every metric over seeds, grouped by `keys`."""
    groups: dict[tuple, list[dict]] = {}
    for r in rows:
        groups.setdefault(tuple(r[k] for k in keys), []).append(r)
    metrics = ["wait_avg", "wait_p95", "wait_max", "total_avg", "total_p95", "total_max", "floors_moved", "transfers"]
    out = []
    for key, group in groups.items():
        out.append({**dict(zip(keys, key)), "runs": len(group),
                    **{m: statistics.mean(r[m] for r in group) for m in metrics}})
    return out


def md_table(rows: list[dict], columns: list[tuple[str, str]]) -> str:
    head = "| " + " | ".join(label for _, label in columns) + " |"
    rule = "|" + "|".join("---" for _ in columns) + "|"
    body = []
    for r in rows:
        cells = []
        for key, _ in columns:
            v = r[key]
            cells.append(f"{v:.1f}" if isinstance(v, float) else ("yes" if v is True else "no" if v is False else str(v)))
        body.append("| " + " | ".join(cells) + " |")
    return "\n".join([head, rule, *body])


def read_runs(path: Path) -> list[dict]:
    """Load runs.csv back with its original types."""
    def convert(value: str):
        if value in ("True", "False"):
            return value == "True"
        for kind in (int, float):
            try:
                return kind(value)
            except ValueError:
                pass
        return value

    with open(path, newline="", encoding="utf-8") as f:
        return [{k: convert(v) for k, v in row.items()} for row in csv.DictReader(f)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elevator_sim.experiments", description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="results", help="output folder (default: %(default)s)")
    parser.add_argument("--seeds", type=int, default=10, help="random seeds per setting (default: %(default)s)")
    parser.add_argument("--quick", action="store_true", help="2 seeds: a fast smoke test")
    parser.add_argument("--workers", type=int, default=None, help="parallel processes (default: one per CPU)")
    parser.add_argument("--redraw", action="store_true",
                        help="skip the simulations: rebuild summary and charts from OUT/runs.csv")
    args = parser.parse_args(argv)
    seeds = 2 if args.quick else args.seeds
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.redraw:
        rows = read_runs(out / "runs.csv")
        seeds = len({r["seed"] for r in rows})
    else:
        cases = plan(seeds)
        print(f"running {len(cases)} simulations ({seeds} seeds per setting)...", flush=True)
        with ProcessPoolExecutor(args.workers) as pool:
            rows = list(pool.map(run_case, cases, chunksize=4))
        with open(out / "runs.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    incomplete = [r for r in rows if r["completed"] != r["passengers"]]
    if incomplete:
        # Averages over only the passengers who got through would flatter the scheduler: refuse.
        print(f"error: {len(incomplete)} runs did not deliver every passenger; see {out / 'runs.csv'}. "
              "No summary or charts written.", file=sys.stderr)
        return 1

    by = {name: [r for r in rows if r["experiment"] == name] for name in ("schedulers", "fleet", "door-time", "fairness")}
    sched = aggregate(by["schedulers"], ["traffic", "door_time", "scheduler"])
    fleet = aggregate(by["fleet"], ["elevators", "scheduler"])
    door = aggregate(by["door-time"], ["door_time", "scheduler"])
    fair = aggregate(by["fairness"], ["passengers", "scheduler", "reserve_seats"])

    timing = [("wait_avg", "avg wait"), ("wait_p95", "p95 wait"), ("total_avg", "avg total"),
              ("total_p95", "p95 total"), ("total_max", "max total")]
    summary = [
        "# Experiment results",
        "",
        f"Generated by `python -m elevator_sim.experiments --seeds {seeds}`. Every row is the mean over "
        f"{seeds} random seeds. Times are in ticks (one tick = one floor of travel). Base building: "
        f"{FLOORS} floors, {ELEVATORS} cars, capacity {CAPACITY}, requests spread over {TICKS} ticks.",
        "",
        "## 1. Schedulers by traffic pattern (600 passengers)",
        "",
        md_table(sorted(sched, key=lambda r: (list(TRAFFIC).index(r["traffic"]), r["door_time"],
                                              SCHEDULER_ORDER.index(r["scheduler"]))),
                 [("traffic", "traffic"), ("door_time", "door time"), ("scheduler", "scheduler"), *timing,
                  ("floors_moved", "floors moved"), ("transfers", "transfers")]),
        "",
        "## 2. Fleet size (mixed traffic, 600 passengers, free stops)",
        "",
        md_table(sorted(fleet, key=lambda r: (r["elevators"], r["scheduler"])),
                 [("elevators", "cars"), ("scheduler", "scheduler"), *timing]),
        "",
        "## 3. Door time (up-peak, 40 floors, 300 passengers)",
        "",
        md_table(sorted(door, key=lambda r: (r["door_time"], r["scheduler"])),
                 [("door_time", "door time"), ("scheduler", "scheduler"), *timing, ("transfers", "transfers")]),
        "",
        "## 4. Seat reservation as load rises (mixed traffic, capacity 4)",
        "",
        md_table(sorted(fair, key=lambda r: (r["passengers"], r["scheduler"], r["reserve_seats"])),
                 [("passengers", "passengers"), ("scheduler", "scheduler"), ("reserve_seats", "reserve seats"),
                  ("wait_avg", "avg wait"), ("wait_p95", "p95 wait"), ("wait_max", "max wait"),
                  ("total_avg", "avg total")]),
        "",
    ]
    (out / "summary.md").write_text("\n".join(summary), encoding="utf-8")
    print(f"wrote {out / 'runs.csv'} and {out / 'summary.md'}")

    try:
        from . import charts
    except ImportError as e:  # matplotlib is optional
        print(f"charts skipped ({e}); pip install matplotlib to draw them")
        return 0
    for path in charts.draw_all(sched, fleet, door, fair, out):
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
