"""Helpers shared by the generators."""

from __future__ import annotations

from typing import Iterable

from ..models import Passenger


def check_basics(passengers: int, ticks: int, num_floors: int) -> None:
    if passengers < 0 or ticks < 1:
        raise ValueError("passengers must be >= 0 and ticks >= 1")
    if num_floors < 2:
        raise ValueError("num_floors must be >= 2")


def as_passengers(trips: Iterable[tuple[int, int, int]]) -> list[Passenger]:
    """Turn (time, source, destination) tuples into Passengers numbered p1, p2, ... in time order."""
    ordered = sorted(trips, key=lambda t: t[0])
    return [Passenger(f"p{i}", s, d, t) for i, (t, s, d) in enumerate(ordered, start=1)]
