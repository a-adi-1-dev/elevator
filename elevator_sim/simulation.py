"""The master event loop."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import Iterable

from .building import Building
from .config import SimulationConfig
from .feed import RequestFeed
from .metrics import ElevatorStats, Stats
from .models import Elevator, ElevatorTrip, Journey, Passenger, RideRequest, RuleViolationError
from .observers import TickObserver
from .schedulers.base import Scheduler

log = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SimulationResult:
    ticks: int  # number of ticks simulated
    timed_out: bool  # True if max_ticks was hit before all journeys completed
    journeys: tuple[Journey, ...]
    elevators: tuple[ElevatorStats, ...] = ()

    @property
    def trips(self) -> tuple[ElevatorTrip, ...]:
        """Every individual ride, grouped by passenger."""
        return tuple(r for j in self.journeys for r in j.rides)

    @property
    def completed(self) -> tuple[Journey, ...]:
        return tuple(j for j in self.journeys if j.is_complete)

    @property
    def wait_stats(self) -> Stats | None:
        """Time spent waiting for elevators (incl. at transfers), over completed journeys."""
        return Stats.of(j.wait_time for j in self.completed)

    @property
    def travel_stats(self) -> Stats | None:
        """Time inside elevators (total - wait), over completed journeys."""
        return Stats.of(j.total_time - j.wait_time for j in self.completed)

    @property
    def total_stats(self) -> Stats | None:
        """Request -> arrival at final destination, over completed journeys."""
        return Stats.of(j.total_time for j in self.completed)

    @property
    def longest_wait(self) -> Journey | None:
        """The completed journey with the most waiting (earliest request wins ties)."""
        return max(self.completed, key=lambda j: j.wait_time, default=None)

    def summary(self) -> str:
        done = self.completed
        lines = [
            f"ticks simulated : {self.ticks}" + ("  (hit max_ticks)" if self.timed_out else ""),
            f"requests        : {len(self.journeys)}",
            f"completed       : {len(done)}",
        ]
        if len(done) < len(self.journeys):
            lines.append(f"incomplete      : {len(self.journeys) - len(done)} (excluded from stats)")
        transfers = sum(j.transfers for j in self.journeys)
        if transfers:
            lines.append(f"transfers       : {transfers}")
        lines.append("")
        if not done:
            lines.append("no completed trips - no timing statistics")
            return "\n".join(lines)
        lines.append(f"{'':<13}{'min':>6}{'p50':>6}{'p95':>6}{'max':>6}{'avg':>9}")
        for label, stats in (
            ("wait time", self.wait_stats), ("travel time", self.travel_stats), ("total time", self.total_stats)
        ):
            lines.append(
                f"{label:<13}{stats.min:>6}{stats.p50:>6}{stats.p95:>6}{stats.max:>6}{stats.mean:>9.2f}"
            )
        worst = self.longest_wait
        p = worst.passenger
        lines += [
            "",
            f"longest wait : {p.passenger_id} waited {worst.wait_time} ticks "
            f"(floor {p.source_floor} -> {p.destination_floor}, requested at t={p.request_time})",
        ]
        if self.elevators:
            lines += ["", f"{'elevator':<10}{'floors moved':>13}{'stops':>7}{'carried':>9}{'peak load':>11}{'moving':>8}"]
            for e in self.elevators:
                moving = e.floors_travelled / self.ticks if self.ticks else 0
                lines.append(
                    f"{e.elevator_id:<10}{e.floors_travelled:>13}{e.stops:>7}{e.passengers_carried:>9}"
                    f"{e.peak_load:>11}{moving:>8.0%}"
                )
        return "\n".join(lines)


class Simulation:
    """Steps the world forward one tick at a time.

    Order of operations within a tick `now`:
      1. each elevator moves one floor toward its next stop (travel now-1 -> now)
      2. doors open where due; riders whose ride ends here get off
      3. ride requests are assigned an elevator via scheduler.assign() on the
         spot: requests whose time == now, and passengers who just got off to
         change cars (they need their next ride immediately). Steps 2-3 repeat
         if an assignment opened more doors.
      4. waiting passengers board the cars whose doors are open
      5. scheduler.on_tick() plans the next move, seeing the post-boarding state
      6. observers see the end-of-tick state (e.g. the position log)

    So all events stamped `now` (arrival, pickup, dropoff) happen at time `now`,
    and the scheduler always gets a planning step between any change in an
    elevator's work and that elevator's next move.

    Model rule (default, door_time=0): opening/closing doors, boarding and
    alighting take zero ticks.
    A car that stops at a floor at tick t can be one floor further on at t+1,
    exactly as if it had not stopped; the only thing that costs time is travel.
    The same goes for changing cars: a passenger can step off one car and onto
    another in the same tick. With config.door_time = k > 0, a car that lets
    anyone on or off stays at that floor for the next k ticks instead.

    Model rule: elevators obey the operating rules documented on Elevator
    (direction lock, direction-matched boarding, no skipping, no sitting
    still). Any violation aborts the run with a RuleViolationError stamped with
    the tick it happened on.
    """

    def __init__(
        self,
        config: SimulationConfig,
        passengers: Iterable[Passenger],
        scheduler: Scheduler,
        observers: Iterable[TickObserver] = (),
    ):
        self.config = config
        self.building = Building(config)
        self.now = 0
        self._feed = RequestFeed(passengers)
        self._scheduler = scheduler
        self._observers = tuple(observers)

    def run(self) -> SimulationResult:
        while not self._is_finished():
            if self.now >= self.config.max_ticks:
                log.warning("stopping at max_ticks=%d with trips outstanding", self.config.max_ticks)
                return self._result(timed_out=True)
            self.tick()
            self.now += 1
        return self._result(timed_out=False)

    def _result(self, timed_out: bool) -> SimulationResult:
        elevators = tuple(
            ElevatorStats(e.elevator_id, e.floors_travelled, e.stops_served, e.passengers_carried, e.peak_load)
            for e in self.building.elevators
        )
        return SimulationResult(self.now, timed_out, self.building.journeys, elevators)

    def tick(self) -> None:
        try:
            for elevator in self.building.elevators:
                elevator.move()

            doors_open: set[int] = set()
            needs_ride = [(p, p.source_floor) for p in self._feed.release(self.now)]
            needs_ride += self._open_doors(doors_open)
            new_trips: list[ElevatorTrip] = []
            while needs_ride:
                new_trips += [self._start_ride(p, floor) for p, floor in needs_ride]
                needs_ride = self._open_doors(doors_open)

            for elevator in self.building.elevators:
                if elevator.elevator_id in doors_open:
                    self._board(elevator)

            self._scheduler.on_tick(self.now, new_trips, self.building)
        except RuleViolationError as e:
            e.time = self.now
            raise

        for observer in self._observers:
            observer.on_tick_end(self.now, self.building)

    def _start_ride(self, passenger: Passenger, floor: int) -> ElevatorTrip:
        """Request and assign the passenger's next ride, starting from `floor`."""
        request = RideRequest(passenger, floor, passenger.destination_floor, self.now)
        via = self._scheduler.transfer_floor(self.now, request, self.building)
        if via is not None:
            if via in (floor, passenger.destination_floor) or not 1 <= via <= self.config.num_floors:
                raise RuntimeError(f"scheduler gave invalid transfer floor {via} for {request}")
            request = replace(request, destination_floor=via)

        elevator = self._scheduler.assign(self.now, request, self.building)
        if not any(elevator is e for e in self.building.elevators):
            raise RuntimeError(
                f"scheduler returned {elevator!r} for passenger {passenger.passenger_id}, "
                "which is not an elevator in this building"
            )
        trip = self.building.add_request(request, elevator.elevator_id)
        log.debug("t=%d request %s: %d -> %d, assigned E%d", self.now, passenger.passenger_id,
                  request.source_floor, request.destination_floor, elevator.elevator_id)
        return trip

    def _open_doors(self, doors_open: set[int]) -> list[tuple[Passenger, int]]:
        """Open doors wherever they are due and let riders off.

        Returns the passengers who got off to change cars, with the floor.
        """
        transferring = []
        for elevator in self.building.elevators:
            # Always call open_doors(): on a car whose doors are already open it
            # just consumes a stop re-queued at this floor.
            if not elevator.open_doors() or elevator.elevator_id in doors_open:
                continue
            doors_open.add(elevator.elevator_id)
            for trip in self.building.unload(elevator, self.now):
                log.debug("t=%d E%d floor %d: %s alights", self.now, elevator.elevator_id,
                          elevator.current_floor, trip.passenger_id)
                if not trip.request.is_final:
                    transferring.append((trip.passenger, elevator.current_floor))
        return transferring

    def _board(self, elevator: Elevator) -> None:
        waiting = self.building.waiting_at(elevator.current_floor)
        if not waiting:
            return
        for trip in self._scheduler.select_boarders(elevator, waiting, self.now):
            self.building.board(elevator, trip, self.now)
            log.debug("t=%d E%d floor %d: %s boards", self.now, elevator.elevator_id,
                      elevator.current_floor, trip.passenger_id)

    def _is_finished(self) -> bool:
        return self._feed.is_exhausted and not self.building.has_active_trips()
