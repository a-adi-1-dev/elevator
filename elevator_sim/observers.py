"""Read-only hooks into the simulation loop (logging, tracing, live metrics)."""

from __future__ import annotations

import csv
from typing import Protocol, TextIO

from .building import Building


class TickObserver(Protocol):
    def on_tick_end(self, now: int, building: Building) -> None:
        """Called once at the end of every tick, after doors have opened/closed.
        Observers must not mutate the building."""


class PositionLogWriter:
    """Writes one CSV row per tick: the time, then every elevator's floor.

        time,elevator_0,elevator_1
        0,1,1
        1,2,1

    The caller owns `stream` (open it with newline="" and close it afterwards).
    """

    def __init__(self, stream: TextIO, num_elevators: int):
        self._writer = csv.writer(stream)
        self._writer.writerow(["time", *(f"elevator_{i}" for i in range(num_elevators))])

    def on_tick_end(self, now: int, building: Building) -> None:
        self._writer.writerow([now, *(e.current_floor for e in building.elevators)])
