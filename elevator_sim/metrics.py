"""Summary statistics over trip timings."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True, slots=True)
class Stats:
    count: int
    min: int
    max: int
    mean: float
    p50: int  # median (nearest-rank)
    p95: int  # 95th percentile (nearest-rank): 1 in 20 passengers did worse than this

    @classmethod
    def of(cls, values: Iterable[int]) -> Stats | None:
        """Stats for `values`, or None if there are none."""
        data = sorted(values)
        if not data:
            return None
        return cls(len(data), data[0], data[-1], mean(data), percentile(data, 50), percentile(data, 95))


def percentile(sorted_data: Sequence[int], q: float) -> int:
    """Nearest-rank percentile: the smallest value with at least q% of the data at or below it.

    Always one of the observed values, so it stays an integer number of ticks.
    """
    if not sorted_data:
        raise ValueError("percentile of empty data")
    if not 0 < q <= 100:
        raise ValueError(f"q must be in (0, 100], got {q}")
    rank = math.ceil(q / 100 * len(sorted_data))
    return sorted_data[rank - 1]


@dataclass(frozen=True, slots=True)
class ElevatorStats:
    """What one car did over a run."""

    elevator_id: int
    floors_travelled: int
    stops: int  # times the doors opened to let someone on or off
    passengers_carried: int
    peak_load: int
