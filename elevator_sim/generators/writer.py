"""Write generated requests as a CSV the simulator can load."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable

from ..loader import REQUIRED_COLUMNS
from ..models import Passenger


def write_requests(path: str | Path, passengers: Iterable[Passenger]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(REQUIRED_COLUMNS)
        for p in passengers:
            writer.writerow([p.request_time, p.passenger_id, p.source_floor, p.destination_floor])
