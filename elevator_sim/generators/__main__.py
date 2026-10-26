"""Command-line entry point:

    python -m elevator_sim.generators normal data/normal_100.csv --passengers 100 --ticks 200 --floors 10
    python -m elevator_sim.generators random data/random_100.csv --passengers 100 --ticks 200 --floors 10
"""

from __future__ import annotations

import argparse
import sys

from .normal import LOBBY, generate_normal
from .random import generate_random
from .writer import write_requests


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="elevator_sim.generators", description="Generate a request CSV.")
    patterns = parser.add_subparsers(dest="pattern", required=True, metavar="PATTERN")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("output", help="CSV file to write")
    common.add_argument("--passengers", type=int, required=True)
    common.add_argument("--ticks", type=int, required=True, help="requests are made at times 0..ticks-1")
    common.add_argument("--floors", type=int, required=True)
    common.add_argument("--seed", type=int, help="random seed, for reproducible output")

    normal = patterns.add_parser("normal", parents=[common], help="lobby-heavy traffic")
    normal.add_argument("--from-lobby", type=float, default=0.4, help="share of trips starting at floor 1")
    normal.add_argument("--to-lobby", type=float, default=0.4, help="share of trips ending at floor 1")
    patterns.add_parser("random", parents=[common], help="every pair of floors equally likely")

    args = parser.parse_args(argv)
    try:
        if args.pattern == "normal":
            passengers = generate_normal(
                args.passengers, args.ticks, args.floors, args.from_lobby, args.to_lobby, args.seed
            )
        else:
            passengers = generate_random(args.passengers, args.ticks, args.floors, args.seed)
        write_requests(args.output, passengers)
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    lobby_in = sum(p.source_floor == LOBBY for p in passengers)
    lobby_out = sum(p.destination_floor == LOBBY for p in passengers)
    print(f"wrote {len(passengers)} requests to {args.output}: "
          f"{lobby_in} from lobby, {lobby_out} to lobby, {len(passengers) - lobby_in - lobby_out} between floors")
    return 0


if __name__ == "__main__":
    sys.exit(main())
