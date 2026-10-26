"""Simulation parameters."""

from __future__ import annotations

from dataclasses import dataclass

MAX_ELEVATORS = 10
DEFAULT_MAX_TICKS = 100_000  # safety stop so a stuck scheduler cannot loop forever


@dataclass(frozen=True, slots=True)
class SimulationConfig:
    num_elevators: int
    num_floors: int
    capacity: int  # max passengers per elevator
    max_ticks: int = DEFAULT_MAX_TICKS
    door_time: int = 0  # ticks a car waits at a floor after someone boards or gets off

    def __post_init__(self) -> None:
        if not 1 <= self.num_elevators <= MAX_ELEVATORS:
            raise ValueError(f"num_elevators must be in 1..{MAX_ELEVATORS}, got {self.num_elevators}")
        if self.num_floors < 2:
            raise ValueError(f"num_floors must be >= 2, got {self.num_floors}")
        if self.capacity < 1:
            raise ValueError(f"capacity must be >= 1, got {self.capacity}")
        if self.door_time < 0:
            raise ValueError(f"door_time must be >= 0, got {self.door_time}")
        if self.max_ticks < 1:
            raise ValueError(f"max_ticks must be >= 1, got {self.max_ticks}")
