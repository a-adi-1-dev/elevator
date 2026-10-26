"""Zone scheduler: each elevator serves floor 1 plus one block of consecutive floors.

Floors 2..N are split into blocks of (nearly) equal size, one per elevator,
the lowest block going to elevator 0; any leftover floors go to the lower
blocks. If there are more elevators than floors above the lobby, blocks are
shared: elevator i serves block i mod (number of blocks).

A ride to or from floor 1, or within one block, is served by that block's
car(s). A trip between two different blocks changes cars at floor 1: down to
the lobby in the source block's car, then up in the destination block's car.

Among a block's cars, the ride goes to the one with the soonest pickup, and
cars are routed exactly as NearestCarScheduler routes them. Cars only stop at
their own passengers' floors, so they only serve their block and the lobby
(they do pass through other blocks on the way).
"""

from __future__ import annotations

from typing import Sequence

from ..building import Building
from ..models import Elevator, RideRequest
from .nearest_car import NearestCarScheduler

LOBBY = 1


class ZoneScheduler(NearestCarScheduler):
    def __init__(self) -> None:
        self._blocks: list[range] | None = None

    def blocks(self, building: Building) -> list[range]:
        """The floor blocks above the lobby; elevator i serves block i mod len(blocks)."""
        if self._blocks is None:
            self._blocks = split_floors(building.num_floors, len(building.elevators))
        return self._blocks

    def zone(self, elevator: Elevator, building: Building) -> list[int]:
        """Every floor `elevator` serves: the lobby plus its block."""
        blocks = self.blocks(building)
        return [LOBBY, *blocks[elevator.elevator_id % len(blocks)]]

    def transfer_floor(self, now: int, request: RideRequest, building: Building) -> int | None:
        if LOBBY in (request.source_floor, request.destination_floor):
            return None
        if self._block_of(request.source_floor, building) == self._block_of(request.destination_floor, building):
            return None
        return LOBBY

    def candidates(self, request: RideRequest, building: Building) -> Sequence[Elevator]:
        # Every ride has at most one non-lobby block (transfer_floor saw to that).
        upper = request.source_floor if request.source_floor != LOBBY else request.destination_floor
        block = self._block_of(upper, building)
        cars = [e for e in building.elevators if e.elevator_id % len(self.blocks(building)) == block]
        for e in cars:
            served = self.zone(e, building)
            if request.source_floor not in served or request.destination_floor not in served:
                raise RuntimeError(f"ride {request} crosses zones; it should have been split at the lobby")
        return cars

    def _block_of(self, floor: int, building: Building) -> int:
        for i, block in enumerate(self.blocks(building)):
            if floor in block:
                return i
        raise ValueError(f"floor {floor} is not above the lobby")


def split_floors(num_floors: int, num_elevators: int) -> list[range]:
    """Split floors 2..num_floors into min(num_elevators, num_floors - 1) consecutive blocks."""
    upper = range(LOBBY + 1, num_floors + 1)
    count = min(num_elevators, len(upper))
    size, extra = divmod(len(upper), count)
    blocks, start = [], upper.start
    for i in range(count):
        end = start + size + (1 if i < extra else 0)
        blocks.append(range(start, end))
        start = end
    return blocks
