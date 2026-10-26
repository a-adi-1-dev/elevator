"""Core domain objects: Passenger, ElevatorTrip, Elevator.

Floors are 1-indexed (1..num_floors). Time is measured in integer ticks, where
one tick is the time it takes an elevator to travel one floor.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable


class Direction(Enum):
    UP = 1
    DOWN = -1
    IDLE = 0


class TripStatus(Enum):
    # There is deliberately no unassigned state: a trip is created already
    # assigned, at the tick its request is released.
    ASSIGNED = "assigned"    # an elevator is committed; passenger still at source
    RIDING = "riding"        # passenger is inside an elevator
    COMPLETED = "completed"  # passenger has arrived at their destination


class InvalidTransitionError(RuntimeError):
    """Raised when an ElevatorTrip is moved through an illegal state change."""


class RuleViolationError(RuntimeError):
    """A scheduler made an elevator break an operating rule. Aborts the run.

    `time` is filled in by the Simulation with the tick it happened on.
    """

    time: int | None = None


class DirectionViolationError(RuleViolationError):
    """Reversing while locked, or boarding a passenger going against a locked direction."""


class SkipViolationError(RuleViolationError):
    """Leaving a floor without serving a rider getting off, or an assigned passenger who could board."""


class StallViolationError(RuleViolationError):
    """A car with riders or assigned passengers was given nowhere to go."""


@dataclass(frozen=True, slots=True)
class Passenger:
    """One input request: who wants to go where, and when they asked.

    Immutable - this is the "what was asked" half. Serving it takes one or more
    elevator rides (RideRequest / ElevatorTrip), tracked together as a Journey.
    """

    passenger_id: str
    source_floor: int
    destination_floor: int
    request_time: int

    def __post_init__(self) -> None:
        if self.request_time < 0:
            raise ValueError(f"request_time must be >= 0, got {self.request_time}")
        if self.source_floor == self.destination_floor:
            raise ValueError(
                f"passenger {self.passenger_id}: source and destination are both {self.source_floor}"
            )

    @property
    def direction(self) -> Direction:
        return Direction.UP if self.destination_floor > self.source_floor else Direction.DOWN

    @property
    def distance(self) -> int:
        return abs(self.destination_floor - self.source_floor)


@dataclass(frozen=True, slots=True)
class RideRequest:
    """One elevator ride a passenger needs, asked for at `time`.

    A direct trip is a single ride from the passenger's source to their
    destination. A trip with a transfer is several rides, each requested the
    moment the previous one ends.
    """

    passenger: Passenger
    source_floor: int
    destination_floor: int
    time: int

    def __post_init__(self) -> None:
        if self.source_floor == self.destination_floor:
            raise ValueError(f"ride for {self.passenger_id} starts and ends on floor {self.source_floor}")

    @classmethod
    def direct(cls, passenger: Passenger) -> RideRequest:
        """The whole trip as one ride."""
        return cls(passenger, passenger.source_floor, passenger.destination_floor, passenger.request_time)

    @property
    def passenger_id(self) -> str:
        return self.passenger.passenger_id

    @property
    def direction(self) -> Direction:
        return Direction.UP if self.destination_floor > self.source_floor else Direction.DOWN

    @property
    def is_final(self) -> bool:
        """True if this ride ends at the passenger's destination."""
        return self.destination_floor == self.passenger.destination_floor


@dataclass(slots=True)
class ElevatorTrip:
    """The lifecycle of serving one RideRequest, from request to drop-off.

    State machine: ASSIGNED -> RIDING -> COMPLETED. The elevator is fixed at
    construction and is final; the passenger may only board that elevator.
    """

    request: RideRequest
    elevator_id: int
    status: TripStatus = field(default=TripStatus.ASSIGNED, init=False)
    pickup_time: int | None = field(default=None, init=False)
    dropoff_time: int | None = field(default=None, init=False)

    @property
    def passenger(self) -> Passenger:
        return self.request.passenger

    @property
    def passenger_id(self) -> str:
        return self.request.passenger_id

    @property
    def source_floor(self) -> int:
        return self.request.source_floor

    @property
    def destination_floor(self) -> int:
        return self.request.destination_floor

    @property
    def direction(self) -> Direction:
        return self.request.direction

    @property
    def awaiting_pickup(self) -> bool:
        return self.status is TripStatus.ASSIGNED

    def board(self, elevator_id: int, now: int) -> None:
        if not self.awaiting_pickup:
            raise InvalidTransitionError(f"cannot board trip in state {self.status.name}")
        if self.elevator_id != elevator_id:
            raise InvalidTransitionError(
                f"trip {self.passenger_id} is assigned to elevator {self.elevator_id}, "
                f"not {elevator_id}"
            )
        self.pickup_time = now
        self.status = TripStatus.RIDING

    def alight(self, now: int) -> None:
        if self.status is not TripStatus.RIDING:
            raise InvalidTransitionError(f"cannot alight trip in state {self.status.name}")
        self.dropoff_time = now
        self.status = TripStatus.COMPLETED

    @property
    def wait_time(self) -> int | None:
        """Ticks from this ride's request until pickup."""
        if self.pickup_time is None:
            return None
        return self.pickup_time - self.request.time

    @property
    def ride_time(self) -> int | None:
        """Ticks spent inside the elevator."""
        if self.pickup_time is None or self.dropoff_time is None:
            return None
        return self.dropoff_time - self.pickup_time

    @property
    def total_time(self) -> int | None:
        """Ticks from this ride's request until drop-off."""
        if self.dropoff_time is None:
            return None
        return self.dropoff_time - self.request.time


@dataclass(slots=True)
class Journey:
    """A passenger's whole trip: one ride, or several with transfers between them."""

    passenger: Passenger
    rides: list[ElevatorTrip] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        last = self.rides[-1] if self.rides else None
        return last is not None and last.status is TripStatus.COMPLETED and last.request.is_final

    @property
    def transfers(self) -> int:
        return max(len(self.rides) - 1, 0)

    @property
    def wait_time(self) -> int | None:
        """Ticks spent waiting for elevators, summed over all rides (incl. at transfers)."""
        if not self.is_complete:
            return None
        return sum(r.wait_time for r in self.rides)

    @property
    def total_time(self) -> int | None:
        """Ticks from the original request until arrival at the final destination."""
        if not self.is_complete:
            return None
        return self.rides[-1].dropoff_time - self.passenger.request_time


class Elevator:
    """A single car: its position, riders, assigned passengers and stop queue.

    The elevator owns the *mechanics* - it moves one floor per tick toward the
    next stop and enforces the operating rules below. It makes no decisions: a
    Scheduler fills its stop queue. accept()/board()/unload() are driven by the
    Simulation via Building; schedulers should not call them directly.

    Operating rules (breaking one raises a RuleViolationError subclass):
      * Direction lock - once heading UP (or DOWN), the car may not reverse
        while any rider who requested that direction is aboard, or any
        passenger assigned to it who requested that direction is waiting
        further along. (DirectionViolationError)
      * Boarding - while locked, only passengers going the locked direction
        may board. When unlocked, boarding commits the car to the boarding
        passenger's direction. (DirectionViolationError)
      * No skipping - the car may not leave a floor where a rider wants to get
        off, or where an assigned passenger going the car's way is waiting and
        there is room. "Room" means a free seat not reserved for an older
        passenger: a car may pass a newer passenger to keep a seat for someone
        who asked earlier, is waiting further along, and is going the same way
        (see reserved_seats). (SkipViolationError)
      * No sitting still - a car with riders or assigned passengers must move
        every tick, except while its doors are held open (see door_time).
        (StallViolationError)

    Door time: whenever someone boards or gets off, the car stays at that floor
    for the next `door_time` ticks before it can move again (each further
    boarding restarts the hold). door_time=0, the default, is the brief's model,
    where stopping costs nothing.
    """

    def __init__(
        self, elevator_id: int, capacity: int, num_floors: int, start_floor: int = 1, door_time: int = 0
    ):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        if not 1 <= start_floor <= num_floors:
            raise ValueError(f"start_floor {start_floor} outside 1..{num_floors}")
        if door_time < 0:
            raise ValueError("door_time must be >= 0")
        self.elevator_id = elevator_id
        self.capacity = capacity
        self.num_floors = num_floors
        self.current_floor = start_floor
        self._stops: list[int] = []
        self._riders: dict[str, ElevatorTrip] = {}
        self._assigned: dict[str, ElevatorTrip] = {}  # assigned to this car, not yet picked up
        self._heading = Direction.IDLE  # committed direction: last move or last boarding
        self.door_time = door_time
        self._hold = 0  # ticks the doors stay open before the car may move again
        self._held = False  # stayed put this tick to hold the doors (so they are open)
        self._last_service: int | None = None  # last tick anyone boarded or got off
        # running totals, for reporting
        self.floors_travelled = 0
        self.stops_served = 0
        self.passengers_carried = 0
        self.peak_load = 0

    def __repr__(self) -> str:
        return (
            f"Elevator(id={self.elevator_id}, floor={self.current_floor}, "
            f"dir={self.direction.name}, load={self.load}/{self.capacity}, stops={self._stops})"
        )

    # --- state queries ---------------------------------------------------

    @property
    def riders(self) -> tuple[ElevatorTrip, ...]:
        return tuple(self._riders.values())

    @property
    def assigned(self) -> tuple[ElevatorTrip, ...]:
        """Passengers assigned to this car who have not been picked up yet."""
        return tuple(self._assigned.values())

    @property
    def has_work(self) -> bool:
        return bool(self._riders or self._assigned)

    @property
    def load(self) -> int:
        return len(self._riders)

    @property
    def available_capacity(self) -> int:
        return self.capacity - self.load

    @property
    def is_full(self) -> bool:
        return self.load >= self.capacity

    @property
    def stops(self) -> tuple[int, ...]:
        return tuple(self._stops)

    @property
    def is_holding(self) -> bool:
        """True while the doors are held open after a stop (only when door_time > 0)."""
        return self._hold > 0

    @property
    def hold_remaining(self) -> int:
        """Ticks before the car may move again."""
        return self._hold

    @property
    def next_stop(self) -> int | None:
        return self._stops[0] if self._stops else None

    @property
    def is_idle(self) -> bool:
        return not self._stops

    @property
    def locking_trips(self) -> tuple[ElevatorTrip, ...]:
        """The riders and waiting passengers currently holding the direction lock."""
        h = self._heading
        if h is Direction.IDLE:
            return ()
        riding = [t for t in self._riders.values() if t.direction is h]
        ahead = [
            t for t in self._assigned.values()
            if t.direction is h and (t.source_floor - self.current_floor) * h.value > 0
        ]
        return tuple(riding + ahead)

    @property
    def is_direction_locked(self) -> bool:
        return bool(self.locking_trips)

    @property
    def direction(self) -> Direction:
        """The locked direction while locked; otherwise the way to the next stop."""
        if self.is_direction_locked:
            return self._heading
        target = self.next_stop
        if target is None or target == self.current_floor:
            return Direction.IDLE
        return _direction_between(self.current_floor, target)

    def can_move_toward(self, floor: int) -> bool:
        """Whether heading toward `floor` now would respect the direction lock."""
        if floor == self.current_floor or not self.is_direction_locked:
            return True
        return _direction_between(self.current_floor, floor) is self._heading

    def reserved_seats(self, trip: ElevatorTrip, heading: Direction) -> int:
        """Seats to hold back from `trip` (boarding here, heading `heading`) for older passengers.

        Counts this car's assigned passengers who requested at an earlier tick,
        are going `heading`, and are waiting further along in that direction.
        """
        return sum(
            1 for t in self._assigned.values()
            if t.request.time < trip.request.time
            and t.direction is heading
            and (t.source_floor - self.current_floor) * heading.value > 0
        )

    def has_room_for(self, trip: ElevatorTrip, heading: Direction) -> bool:
        """Whether a free seat is left for `trip` after reserving seats for older passengers."""
        return self.available_capacity > self.reserved_seats(trip, heading)

    def can_board(self, trip: ElevatorTrip) -> bool:
        """Whether `trip` may board now under the direction rule (ignores floor and capacity)."""
        return not self.is_direction_locked or trip.direction is self._heading

    # --- stop queue (scheduler-facing) -----------------------------------

    def add_stop(self, floor: int) -> None:
        """Append a stop to the queue unless it is already the last stop.

        A floor can legitimately appear more than once (e.g. [5, 1, 5]), so
        only an immediate repeat is dropped.
        """
        self._validate_floor(floor)
        if not self._stops or self._stops[-1] != floor:
            self._stops.append(floor)

    def set_stops(self, floors: list[int]) -> None:
        """Replace the whole stop queue (for schedulers that re-plan each tick)."""
        for floor in floors:
            self._validate_floor(floor)
        self._stops = list(floors)

    def clear_stops(self) -> None:
        self._stops.clear()

    # --- mechanics (simulation-facing) -----------------------------------

    def move(self) -> None:
        """One tick of motion: travel one floor toward the next stop."""
        self._held = self._hold > 0
        if self._held:
            self._hold -= 1  # doors still open: stay put this tick
            return
        target = self.next_stop
        if target is None or target == self.current_floor:
            if self.has_work:
                raise StallViolationError(
                    f"elevator {self.elevator_id} at floor {self.current_floor} has riders or "
                    f"assigned passengers but no stop to move toward (stops={self._stops})"
                )
            return
        if not self.can_move_toward(target):
            raise DirectionViolationError(
                f"elevator {self.elevator_id} at floor {self.current_floor} is locked "
                f"{self._heading.name} by {_ids(self.locking_trips)}; cannot reverse toward floor {target}"
            )
        heading = _direction_between(self.current_floor, target)
        self._check_not_skipping(heading)
        self._heading = heading
        self.current_floor += heading.value
        self.floors_travelled += 1

    def open_doors(self) -> bool:
        """Return True if the doors open at the current floor this tick.

        They open when the car is at its next stop (which is then cleared from
        the queue), when the car is idle, or while they are being held open
        after a stop (door_time > 0). With door_time=0, opening and closing are
        instantaneous: they do not delay the car's next move().
        """
        if self._stops and self._stops[0] == self.current_floor:
            self._stops.pop(0)
            return True
        return not self._stops or self._held

    def accept(self, trip: ElevatorTrip) -> None:
        """Take on a newly assigned trip (passenger still waiting at their floor)."""
        if trip.elevator_id != self.elevator_id:
            raise RuntimeError(f"trip {trip.passenger_id} is assigned to elevator {trip.elevator_id}")
        self._assigned[trip.passenger_id] = trip

    def board(self, trip: ElevatorTrip, now: int) -> None:
        if trip.passenger_id not in self._assigned:
            raise RuntimeError(f"passenger {trip.passenger_id} is not waiting for elevator {self.elevator_id}")
        if self.is_full:
            raise RuntimeError(f"elevator {self.elevator_id} is full")
        if trip.source_floor != self.current_floor:
            raise RuntimeError(
                f"passenger {trip.passenger_id} is on floor {trip.source_floor}, "
                f"elevator {self.elevator_id} is on floor {self.current_floor}"
            )
        if not self.can_board(trip):
            raise DirectionViolationError(
                f"passenger {trip.passenger_id} wants to go {trip.direction.name} but "
                f"elevator {self.elevator_id} is locked {self._heading.name} by {_ids(self.locking_trips)}"
            )
        trip.board(self.elevator_id, now)
        del self._assigned[trip.passenger_id]
        self._riders[trip.passenger_id] = trip
        self._heading = trip.direction
        self.passengers_carried += 1
        self.peak_load = max(self.peak_load, self.load)
        self._served(now)

    def unload(self, now: int) -> list[ElevatorTrip]:
        """Drop off every rider whose destination is the current floor."""
        arrived = [
            t for t in self._riders.values()
            if t.destination_floor == self.current_floor
        ]
        for trip in arrived:
            trip.alight(now)
            del self._riders[trip.passenger_id]
        if arrived:
            self._served(now)
        return arrived

    def _served(self, now: int) -> None:
        """Someone got on or off at tick `now`: count the stop and hold the doors."""
        if self._last_service != now:
            self.stops_served += 1
            self._last_service = now
        self._hold = self.door_time

    def _check_not_skipping(self, heading: Direction) -> None:
        floor = self.current_floor
        missed = [t for t in self._riders.values() if t.destination_floor == floor]
        if missed:
            raise SkipViolationError(
                f"elevator {self.elevator_id} would carry {_ids(missed)} past their destination floor {floor}"
            )
        left_behind = [
            t for t in self._assigned.values()
            if t.source_floor == floor and t.direction is heading and self.has_room_for(t, heading)
        ]
        if left_behind:
            raise SkipViolationError(
                f"elevator {self.elevator_id} would leave floor {floor} going {heading.name} "
                f"without picking up {_ids(left_behind)}, who are going that way and fit"
            )

    def _validate_floor(self, floor: int) -> None:
        if not 1 <= floor <= self.num_floors:
            raise ValueError(f"floor {floor} outside 1..{self.num_floors}")


def _direction_between(from_floor: int, to_floor: int) -> Direction:
    return Direction.UP if to_floor > from_floor else Direction.DOWN


def _ids(trips: Iterable[ElevatorTrip]) -> list[str]:
    return [t.passenger_id for t in trips]
