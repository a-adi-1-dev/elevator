"""Lobby-heavy ("normal" building) traffic.

Each trip is one of three kinds, picked at random by share:
  * from the lobby: floor 1 -> a random upper floor  (people arriving)
  * to the lobby:   a random upper floor -> floor 1  (people leaving)
  * between floors: one upper floor -> another       (everything else)
Request times are spread uniformly over the time span. A seed makes the
output reproducible.
"""

from __future__ import annotations

import random

from ..models import Passenger
from .base import as_passengers, check_basics

LOBBY = 1


def generate_normal(
    passengers: int,
    ticks: int,
    num_floors: int,
    from_lobby: float = 0.4,
    to_lobby: float = 0.4,
    seed: int | None = None,
) -> list[Passenger]:
    """Random requests, sorted by time. Whatever share is left after
    `from_lobby` and `to_lobby` is trips between upper floors."""
    check_basics(passengers, ticks, num_floors)
    between = 1 - from_lobby - to_lobby
    if from_lobby < 0 or to_lobby < 0 or between < -1e-9:
        raise ValueError("from_lobby and to_lobby must be >= 0 and add up to at most 1")
    if between > 1e-9 and num_floors < 3:
        raise ValueError("trips between upper floors need at least 3 floors")

    rng = random.Random(seed)
    upper = range(LOBBY + 1, num_floors + 1)
    trips = []
    for _ in range(passengers):
        kind = rng.choices(("from", "to", "between"), weights=(from_lobby, to_lobby, max(between, 0)))[0]
        if kind == "from":
            source, destination = LOBBY, rng.choice(upper)
        elif kind == "to":
            source, destination = rng.choice(upper), LOBBY
        else:
            source, destination = rng.sample(upper, 2)
        trips.append((rng.randrange(ticks), source, destination))
    return as_passengers(trips)
