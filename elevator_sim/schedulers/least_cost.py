"""Least-cost dispatch: give each request to the car where it adds the least total time.

Nearest-car asks "which car can pick this person up soonest?" That ignores
what the pickup costs everyone else: each extra stop holds the doors (when
door_time > 0) for every passenger already aboard or waiting for that car.

This scheduler prices that in. For each candidate car it plans the car's route
twice, without and with the new passenger, and estimates when every one of the
car's passengers (riders, people waiting for it, and the newcomer) would
arrive. Arrival at a stop = travel so far + door_time for every earlier stop.
The request goes to the car where the sum of arrival times grows least: the
newcomer's own wait + ride, plus the delay they cause others. That is the
brief's objective (minimise total time per passenger) applied greedily, one
request at a time.

Routing is unchanged from NearestCarScheduler (LOOK sweeps), so the operating
rules hold for the same reasons. Ties go to the sooner pickup, then the lower id.
"""

from __future__ import annotations

from ..building import Building
from ..models import Elevator, RideRequest
from .nearest_car import NearestCarScheduler, Pickup, _pickup_eta, can_board_now, plan_for, plan_route


class LeastCostScheduler(NearestCarScheduler):
    def choose_car(self, request: RideRequest, building: Building) -> Elevator:
        def key(car: Elevator):
            return (marginal_cost(car, request), _pickup_eta(car, request), car.elevator_id)

        return min(self.candidates(request, building), key=key)


def marginal_cost(car: Elevator, request: RideRequest) -> float:
    """Estimated extra passenger-ticks if `car` takes `request`."""
    return route_cost(car, request) - route_cost(car)


def route_cost(car: Elevator, extra: RideRequest | None = None) -> float:
    """Sum of estimated ticks until each of the car's passengers arrives (plus `extra`'s)."""
    riders = [t.destination_floor for t in car.riders]
    if extra is not None and can_board_now(car, extra):
        # They step in this tick: plan them as a rider, and the car commits to their direction.
        stops, boarded_at = plan_route(
            floor=car.current_floor,
            direction=extra.direction if not car.is_direction_locked else car.direction,
            locked=True,
            destinations=[*riders, extra.destination_floor],
            pickups=[Pickup.of(t) for t in car.assigned],
            capacity=car.capacity,
        )
        riders.append(extra.destination_floor)
        extra = None
    else:
        stops, boarded_at = plan_for(car, extra)

    arrive = _stop_times(car, stops)
    total = 0.0
    for dest in riders:
        total += _first_visit(stops, arrive, dest, after=-1)
    for p in [*car.assigned, *([extra] if extra is not None else [])]:
        board = boarded_at.get(p.passenger_id)
        if board is None:
            return float("inf")
        total += _first_visit(stops, arrive, p.destination_floor, after=board)
    return total


def _stop_times(car: Elevator, stops: list[int]) -> list[int]:
    """Tick (relative to now) the car reaches each stop."""
    times, t, pos = [], car.hold_remaining, car.current_floor
    for i, floor in enumerate(stops):
        t += abs(floor - pos) + (car.door_time if i else 0)
        times.append(t)
        pos = floor
    return times


def _first_visit(stops: list[int], arrive: list[int], floor: int, after: int) -> float:
    for i in range(after + 1, len(stops)):
        if stops[i] == floor:
            return arrive[i]
    return float("inf")
