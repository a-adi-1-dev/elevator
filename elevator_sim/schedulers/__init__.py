"""Scheduling strategies. Add new ones as modules here and register them below."""

from .base import Scheduler
from .least_cost import LeastCostScheduler
from .naive import NaiveScheduler
from .nearest_car import NearestCarScheduler
from .zone import ZoneScheduler

SCHEDULERS: dict[str, type[Scheduler]] = {
    "least-cost": LeastCostScheduler,
    "naive": NaiveScheduler,
    "nearest-car": NearestCarScheduler,
    "zone": ZoneScheduler,
}



def make_scheduler(name: str, reserve_seats: bool = True) -> Scheduler:
    """A fresh scheduler by command-line name, optionally with seat reservation."""
    scheduler = SCHEDULERS[name]()
    scheduler.reserve_seats_for_older = reserve_seats
    return scheduler


__all__ = ["SCHEDULERS", "make_scheduler", "LeastCostScheduler", "NaiveScheduler", "NearestCarScheduler", "Scheduler", "ZoneScheduler"]
