"""Building: the shared world state a Scheduler observes and acts on."""

from __future__ import annotations

from collections import defaultdict

from .config import SimulationConfig
from .models import Elevator, ElevatorTrip, Journey, RideRequest


class Building:
    """Holds the elevators and every released ride, grouped into journeys.

    State-changing operations that must stay consistent across several objects
    (boarding, unloading) go through here, not straight to the Elevator.
    """

    def __init__(self, config: SimulationConfig):
        self.num_floors = config.num_floors
        self.door_time = config.door_time
        self.elevators: tuple[Elevator, ...] = tuple(
            Elevator(i, config.capacity, config.num_floors, door_time=config.door_time)
            for i in range(config.num_elevators)
        )
        self._journeys: dict[str, Journey] = {}
        self._waiting: dict[int, list[ElevatorTrip]] = defaultdict(list)
        self._active_count = 0  # journeys not yet complete

    # --- queries ---------------------------------------------------------

    @property
    def journeys(self) -> tuple[Journey, ...]:
        """Every passenger's journey so far, in order of first request."""
        return tuple(self._journeys.values())

    @property
    def trips(self) -> tuple[ElevatorTrip, ...]:
        """Every ride released so far, grouped by passenger."""
        return tuple(r for j in self._journeys.values() for r in j.rides)

    def waiting_at(self, floor: int) -> tuple[ElevatorTrip, ...]:
        """Rides whose passenger is standing at `floor` (already assigned), in request order."""
        return tuple(self._waiting.get(floor, ()))

    def waiting_trips(self) -> tuple[ElevatorTrip, ...]:
        """Every ride whose passenger has not been picked up yet."""
        return tuple(t for trips in self._waiting.values() for t in trips)

    def has_active_trips(self) -> bool:
        return self._active_count > 0

    # --- mutations (simulation-facing) -----------------------------------

    def add_request(self, request: RideRequest, elevator_id: int) -> ElevatorTrip:
        """Record a released ride together with its (mandatory) elevator assignment."""
        if not 0 <= elevator_id < len(self.elevators):
            raise ValueError(f"no elevator with id {elevator_id}")
        trip = ElevatorTrip(request, elevator_id)
        self.elevators[elevator_id].accept(trip)
        journey = self._journeys.get(request.passenger_id)
        if journey is None:
            journey = self._journeys[request.passenger_id] = Journey(request.passenger)
            self._active_count += 1
        journey.rides.append(trip)
        self._waiting[request.source_floor].append(trip)
        return trip

    def board(self, elevator: Elevator, trip: ElevatorTrip, now: int) -> None:
        elevator.board(trip, now)
        self._waiting[trip.source_floor].remove(trip)

    def unload(self, elevator: Elevator, now: int) -> list[ElevatorTrip]:
        arrived = elevator.unload(now)
        self._active_count -= sum(1 for t in arrived if t.request.is_final)
        return arrived
