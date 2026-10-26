"""Scheduler interface. Scheduling strategies subclass this."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Sequence

from ..building import Building
from ..models import Direction, Elevator, ElevatorTrip, RideRequest


class Scheduler(ABC):
    """Decides which elevator serves which ride, and where elevators go.

    A scheduler only learns about a request when it is released to it; it
    never has access to the full request list.

    Stop plans must respect the operating rules documented on Elevator; the
    run aborts on the first violation. Elevator.can_move_toward(),
    can_board(), is_direction_locked and locking_trips help with planning.

    reserve_seats_for_older (on by default) makes boarding hold seats for
    passengers who asked earlier and are waiting further along the car's way,
    so newer passengers can't keep taking every seat. See "Fairness" in the
    README and tests/test_fairness.py.
    """

    reserve_seats_for_older: bool = True

    def transfer_floor(self, now: int, request: RideRequest, building: Building) -> int | None:
        """Where the passenger should change cars, or None to ride direct.

        Called for every ride request just before assign(). If a floor is
        returned, this ride ends there and the passenger immediately requests
        a new ride from there to their destination. Default: always direct.
        """
        return None

    @abstractmethod
    def assign(self, now: int, request: RideRequest, building: Building) -> Elevator:
        """Choose the elevator for a ride requested at tick `now`. Required.

        Called once per ride, at the tick it is requested: for a new passenger,
        the tick their request is released; for a transfer, the tick they get
        off their previous car. Doors have opened and riders have got off, but
        nobody has boarded yet. The returned elevator must be one of
        building.elevators, and the choice is final. Assignments made earlier
        in the same tick are already visible in `building`.

        To pick the passenger up this very tick from a car that is already on
        their floor but not stopping there, put that floor at the front of the
        car's stops here - by on_tick() boarding is over.
        """

    def on_tick(self, now: int, new_trips: Sequence[ElevatorTrip], building: Building) -> None:
        """Planning hook, called every tick after doors have opened and closed,
        before the next move. `new_trips` are the rides assigned this tick,
        transfers included. Edit elevator stop queues (add_stop / set_stops /
        clear_stops) here. Default: do nothing.
        """

    def select_boarders(
        self, elevator: Elevator, waiting: Sequence[ElevatorTrip], now: int
    ) -> Sequence[ElevatorTrip]:
        """Pick which waiting passengers step into `elevator` when its doors open.

        Only trips assigned to this elevator may board, and only in one
        direction (see Elevator's boarding rule). Default: if the car is
        locked, its locked direction; otherwise the direction of its next
        stop, or failing that of the earliest request. Then everyone assigned
        and going that way, in request order, up to free capacity - less any
        seats reserved for older passengers if reserve_seats_for_older is set.
        """
        mine = [t for t in waiting if t.elevator_id == elevator.elevator_id]
        if not mine:
            return []
        direction = elevator.direction
        if direction is Direction.IDLE:
            direction = mine[0].direction
        going_my_way = [t for t in mine if t.direction is direction]
        if not self.reserve_seats_for_older:
            return going_my_way[: elevator.available_capacity]
        boarders: list[ElevatorTrip] = []
        for trip in going_my_way:
            if len(boarders) + elevator.reserved_seats(trip, direction) < elevator.available_capacity:
                boarders.append(trip)
        return boarders
