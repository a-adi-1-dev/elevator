"""Nearest-car scheduler: give each request to the car that can pick it up soonest,
and route every car LOOK-style (sweep one way serving everyone going that way, then turn).

Assignment: each new request goes to the elevator with the shortest estimated
pickup time, found by planning that elevator's route with the new passenger
added. Ties go to the less busy elevator, then the lower id.

Routing (re-planned for every elevator every tick, in on_tick):
  * While heading one way, stop at every rider's destination and every
    assigned passenger waiting ahead who is going the same way, nearest first.
  * When nothing more is ahead that way, run on to the farthest passenger
    ahead who is going the other way and turn there; or, if there is none,
    turn where the car is.
  * An idle car heads for the nearest assigned passenger.

The route never reverses while locked and never passes a floor it must stop
at, so it satisfies the operating rules enforced by Elevator. The plan tracks
how full the car will be: passengers who will not fit on this sweep board on a
later one, so pickup estimates account for full cars.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

from ..building import Building
from ..models import Direction, Elevator, ElevatorTrip, RideRequest
from .base import Scheduler


class NearestCarScheduler(Scheduler):
    def candidates(self, request: RideRequest, building: Building) -> Sequence[Elevator]:
        """The elevators allowed to serve `request`. Default: all of them."""
        return building.elevators

    def choose_car(self, request: RideRequest, building: Building) -> Elevator:
        """The car to serve `request`: the soonest pickup."""
        return min(
            self.candidates(request, building),
            key=lambda e: (_pickup_eta(e, request), e.load + len(e.assigned), e.elevator_id),
        )

    def assign(self, now: int, request: RideRequest, building: Building) -> Elevator:
        car = self.choose_car(request, building)
        # The car is already on this floor: open its doors now, before it leaves.
        if car.current_floor == request.source_floor and car.next_stop != request.source_floor:
            car.set_stops([request.source_floor, *car.stops])
        return car

    def on_tick(self, now: int, new_trips: Sequence[ElevatorTrip], building: Building) -> None:
        for car in building.elevators:
            stops, _ = plan_for(car)
            car.set_stops(stops)


# --- route planning --------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Pickup:
    key: str
    source: int
    direction: Direction
    destination: int

    @classmethod
    def of(cls, ride: RideRequest | ElevatorTrip) -> Pickup:
        return cls(ride.passenger_id, ride.source_floor, ride.direction, ride.destination_floor)


def can_board_now(car: Elevator, request: RideRequest) -> bool:
    """Whether the passenger could step into `car` this very tick."""
    return car.current_floor == request.source_floor and not car.is_full and (
        not car.is_direction_locked or car.direction is request.direction
    )


def _pickup_eta(car: Elevator, request: RideRequest) -> float:
    """Estimated ticks until `car` could pick up the passenger for `request`."""
    if can_board_now(car, request):
        return 0
    stops, boarded_at = plan_for(car, extra=request)
    index = boarded_at.get(request.passenger_id)
    if index is None:
        return float("inf")
    return distance(car.current_floor, stops[: index + 1])


def plan_for(car: Elevator, extra: RideRequest | None = None) -> tuple[list[int], dict[str, int]]:
    """Plan `car`'s route from its current state (after this tick's doors)."""
    pickups = [Pickup.of(t) for t in car.assigned]
    if extra is not None:
        pickups.append(Pickup.of(extra))

    # Someone assigned to this car is still standing on its floor (they could
    # not board this time): the car must not leave in their direction, or it
    # would be skipping them.
    forbidden = None
    if not car.is_direction_locked:
        here = [
            t for t in car.assigned
            if t.source_floor == car.current_floor and car.has_room_for(t, t.direction)
        ]
        if here:
            forbidden = here[0].direction

    return plan_route(
        floor=car.current_floor,
        direction=car.direction,
        locked=car.is_direction_locked,
        destinations=[t.destination_floor for t in car.riders],
        pickups=pickups,
        forbidden=forbidden,
        capacity=car.capacity,
    )


def plan_route(
    floor: int,
    direction: Direction,
    locked: bool,
    destinations: Iterable[int],
    pickups: Iterable[Pickup],
    forbidden: Direction | None = None,
    capacity: int | None = None,
) -> tuple[list[int], dict[str, int]]:
    """Plan a LOOK route.

    `destinations` has one entry per rider aboard. With `capacity`, a pickup
    only boards when the car has a free seat at that point in the plan;
    otherwise it waits for a later sweep.

    `floor` is where the car is, with its doors already closed for this tick,
    so passengers waiting there can only board after the car leaves and comes
    back. `direction` is the locked direction if `locked`, else the preferred
    one (IDLE for none). `forbidden` is a direction the car must not leave
    `floor` in.

    Returns (stops, boarded_at): the stop list, and for each pickup the index
    of the stop where it boards.
    """
    pos = floor
    dests = Counter(destinations)  # destination floor -> riders getting off there
    pending = list(pickups)
    stops: list[int] = []
    boarded_at: dict[str, int] = {}

    d = _initial_direction(pos, direction, locked, pending, forbidden)
    if d is Direction.IDLE:
        return stops, boarded_at

    first = True
    while dests or pending:
        nxt = _next_target(pos, d, dests, pending)
        if nxt is None:
            if first and forbidden is not None:
                nxt = pos + d.value  # nothing to do the allowed way: step out and come back
            else:
                d = _opposite(d)
                nxt = _next_target(pos, d, dests, pending)
                if nxt is None:
                    break
        first = False
        stops.append(nxt)
        pos = nxt
        d = _arrive(pos, d, dests, pending, boarded_at, len(stops) - 1, capacity)
    return stops, boarded_at


def _initial_direction(
    pos: int, direction: Direction, locked: bool, pending: list[Pickup], forbidden: Direction | None
) -> Direction:
    if locked:
        return direction
    if forbidden is not None:
        return _opposite(forbidden)
    if not pending:
        return Direction.IDLE
    if direction is not Direction.IDLE:
        for d in (direction, _opposite(direction)):
            if any(_ahead(pos, d, p.source) for p in pending):
                return d
    nearest = min(pending, key=lambda p: abs(p.source - pos))
    if nearest.source == pos:
        return nearest.direction
    return Direction.UP if nearest.source > pos else Direction.DOWN


def _next_target(pos: int, d: Direction, dests: Counter[int], pending: list[Pickup]) -> int | None:
    """Nearest stop ahead that keeps the sweep going; else the farthest
    passenger ahead going the other way (where the car will turn); else None."""
    same_way = [x for x in dests if _ahead(pos, d, x)]
    same_way += [p.source for p in pending if p.direction is d and _ahead(pos, d, p.source)]
    if same_way:
        return min(same_way, key=lambda x: abs(x - pos))
    other_way = [p.source for p in pending if p.direction is not d and _ahead(pos, d, p.source)]
    if other_way:
        return max(other_way, key=lambda x: abs(x - pos))
    return None


def _arrive(
    pos: int, d: Direction, dests: Counter[int], pending: list[Pickup], boarded_at: dict[str, int], index: int,
    capacity: int | None = None,
) -> Direction:
    """Stop at `pos` travelling `d`: drop riders, decide which way to continue,
    board the passengers going that way. Returns the continuing direction.

    Mirrors the simulation's default boarding: a locked car takes its locked
    direction; an unlocked one takes the direction of its next stop, which is
    the direction chosen here.
    """
    dests.pop(pos, None)
    here = [p for p in pending if p.source == pos]
    keep_going = (
        any(p.direction is d for p in here)
        or any(_ahead(pos, d, x) for x in dests)
        or any(_ahead(pos, d, p.source) for p in pending)
    )
    heading = d if keep_going else _opposite(d)
    free = float("inf") if capacity is None else capacity - sum(dests.values())
    for p in here:
        if p.direction is heading and free > 0:
            pending.remove(p)
            dests[p.destination] += 1
            boarded_at[p.key] = index
            free -= 1
    return heading


def _ahead(pos: int, d: Direction, floor: int) -> bool:
    return (floor - pos) * d.value > 0


def _opposite(d: Direction) -> Direction:
    return Direction(-d.value)


def distance(start: int, stops: Iterable[int]) -> int:
    total, pos = 0, start
    for s in stops:
        total += abs(s - pos)
        pos = s
    return total
