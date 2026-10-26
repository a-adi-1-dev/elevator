"""Command-line entry point: python -m elevator_sim requests.csv --elevators 3 --floors 10 --capacity 8"""

from __future__ import annotations

import argparse
import logging
import sys

from .config import DEFAULT_MAX_TICKS, SimulationConfig
from .loader import load_requests
from .models import RuleViolationError
from .observers import PositionLogWriter
from .schedulers import SCHEDULERS, make_scheduler
from .simulation import Simulation


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elevator_sim", description="Run an elevator scheduling simulation.")
    parser.add_argument("requests", help="CSV with columns time,passenger_id,source,destination")
    parser.add_argument("--elevators", type=int, default=3, help="number of elevators, 1-10 (default: %(default)s)")
    parser.add_argument("--floors", type=int,
                        help="number of floors, numbered 1..N (default: the highest floor in the file)")
    parser.add_argument("--capacity", type=int, default=8, help="max passengers per elevator (default: %(default)s)")
    parser.add_argument("--door-time", type=int, default=0, metavar="TICKS",
                        help="ticks a car waits at a floor after anyone boards or gets off "
                             "(default: %(default)s, as in the brief)")
    parser.add_argument("--max-ticks", type=int, default=DEFAULT_MAX_TICKS, help="safety stop")
    parser.add_argument("--scheduler", choices=sorted(SCHEDULERS), default="least-cost",
                        help="(default: %(default)s)")
    parser.add_argument("--reserve-seats", action=argparse.BooleanOptionalAction, default=True,
                        help="hold seats for passengers who asked earlier, so a stream of newer passengers can't keep "
                             "someone waiting (default: on; --no-reserve-seats turns it off for a lower average)")
    parser.add_argument("--positions-log", default="elevator_positions.csv", metavar="PATH",
                        help="CSV of every elevator's floor at each tick (default: %(default)s)")
    parser.add_argument("-v", "--verbose", action="store_true", help="log every event")
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(message)s")

    try:
        passengers = load_requests(args.requests, num_floors=args.floors)
        floors = args.floors or max([2, *(max(p.source_floor, p.destination_floor) for p in passengers)])
        config = SimulationConfig(args.elevators, floors, args.capacity, args.max_ticks, args.door_time)
    except (ValueError, OSError) as e:  # RequestFileError is a ValueError
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        with open(args.positions_log, "w", newline="", encoding="utf-8") as positions:
            recorder = PositionLogWriter(positions, config.num_elevators)
            result = Simulation(config, passengers, make_scheduler(args.scheduler, args.reserve_seats), [recorder]).run()
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except RuleViolationError as e:
        print(f"rule violation at t={e.time} ({type(e).__name__}): {e}", file=sys.stderr)
        print(f"elevator positions up to the violation are in {args.positions_log}", file=sys.stderr)
        return 1

    print(result.summary())
    print(f"\nelevator positions written to {args.positions_log}")
    if result.timed_out:
        undelivered = len(passengers) - len(result.completed)
        print(f"error: stopped at --max-ticks {config.max_ticks} with {undelivered} passenger(s) not delivered",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
