"""Real-time request feed: the only path by which requests enter the simulation."""

from __future__ import annotations

from collections import deque
from typing import Iterable

from .models import Passenger


class RequestFeed:
    """Hands out requests only once the clock reaches their request time.

    Even though every request is known up front, this class exposes no way to
    look ahead: release() returns what is due *now*, and the clock may only move
    forward. The scheduler never receives the feed itself.
    """

    def __init__(self, passengers: Iterable[Passenger]):
        self._pending = deque(sorted(passengers, key=lambda p: p.request_time))
        self._clock: int | None = None

    def release(self, now: int) -> list[Passenger]:
        """Return every request with request_time <= now that has not yet been released."""
        if self._clock is not None and now < self._clock:
            raise ValueError(f"time cannot go backwards ({now} < {self._clock})")
        self._clock = now
        due: list[Passenger] = []
        while self._pending and self._pending[0].request_time <= now:
            due.append(self._pending.popleft())
        return due

    @property
    def is_exhausted(self) -> bool:
        """True once every request has been released. Used only for termination."""
        return not self._pending
