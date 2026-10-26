"""Uniformly random traffic: every pair of floors equally likely, lobby included.

Request times are spread uniformly over the time span. A seed makes the
output reproducible.
"""

from __future__ import annotations

import random

from ..models import Passenger
from .base import as_passengers, check_basics


def generate_random(passengers: int, ticks: int, num_floors: int, seed: int | None = None) -> list[Passenger]:
    """Random requests between two distinct random floors, sorted by time."""
    check_basics(passengers, ticks, num_floors)
    rng = random.Random(seed)
    floors = range(1, num_floors + 1)
    trips = []
    for _ in range(passengers):
        source, destination = rng.sample(floors, 2)
        trips.append((rng.randrange(ticks), source, destination))
    return as_passengers(trips)
