"""Naive baseline: every car shuttles bottom -> top -> bottom, stopping at every floor.

Requests are dealt out to the cars in turn (round-robin), ignoring where the
cars are. Because a car stops at every floor and only turns at the top and
bottom, it never skips anyone, never reverses early and never sits still, so
it obeys every operating rule with no cleverness at all. It is slow on
purpose: a yardstick for smarter schedulers.
"""

from __future__ import annotations

from typing import Sequence

from ..building import Building
from ..models import Elevator, ElevatorTrip, RideRequest
from .base import Scheduler


class NaiveScheduler(Scheduler):
    def __init__(self) -> None:
        self._requests_seen = 0

    def assign(self, now: int, request: RideRequest, building: Building) -> Elevator:
        car = building.elevators[self._requests_seen % len(building.elevators)]
        self._requests_seen += 1
        return car

    def on_tick(self, now: int, new_trips: Sequence[ElevatorTrip], building: Building) -> None:
        # Whenever a car finishes a round trip (it is back at the bottom), queue
        # another one: up through every floor, then back down through every floor.
        top = building.num_floors
        for car in building.elevators:
            if not car.stops:
                here = car.current_floor
                car.set_stops([*range(here + 1, top + 1), *range(top - 1, 0, -1)])
