"""CSV input parsing and validation.

Expected schema (header row required, extra columns ignored):

    time,id,source,dest
    0,passenger1,1,51
    10,passenger3,20,1

Column names are case-insensitive, and each column has a few accepted names
(see COLUMN_ALIASES), so both the brief's `time,id,source,dest` and the
longer `time,passenger_id,source,destination` work.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, TextIO

from .models import Passenger

REQUIRED_COLUMNS = ("time", "passenger_id", "source", "destination")  # canonical names, written by generators

COLUMN_ALIASES: dict[str, tuple[str, ...]] = {
    "time": ("time", "t"),
    "passenger_id": ("passenger_id", "id", "passenger", "passengerid"),
    "source": ("source", "src", "origin", "from"),
    "destination": ("destination", "dest", "dst", "to"),
}


class RequestFileError(ValueError):
    """A problem in the request CSV, tagged with the offending line number."""

    def __init__(self, message: str, line: int | None = None):
        self.line = line
        super().__init__(f"line {line}: {message}" if line is not None else message)


def load_requests(path: str | Path, num_floors: int | None = None) -> list[Passenger]:
    """Read and validate a request CSV from disk. See read_requests()."""
    # utf-8-sig transparently strips the BOM that Excel adds to exported CSVs.
    with open(path, newline="", encoding="utf-8-sig") as f:
        return read_requests(f, num_floors)


def read_requests(stream: TextIO | Iterable[str], num_floors: int | None = None) -> list[Passenger]:
    """Parse request rows into Passengers, sorted by request time.

    If num_floors is given, floors are checked against 1..num_floors.
    Sorting here is only an input convenience; RequestFeed is what guarantees
    the simulation never sees a request before its time.
    """
    reader = csv.DictReader(stream)
    reader.fieldnames = _canonical_header(reader.fieldnames or [])

    passengers: list[Passenger] = []
    seen_ids: set[str] = set()
    for line, row in enumerate(reader, start=2):
        passenger = _parse_row(row, line, num_floors)
        if passenger.passenger_id in seen_ids:
            raise RequestFileError(f"duplicate passenger_id {passenger.passenger_id!r}", line)
        seen_ids.add(passenger.passenger_id)
        passengers.append(passenger)

    # Stable sort keeps file order for requests made at the same tick.
    passengers.sort(key=lambda p: p.request_time)
    return passengers


def _canonical_header(fieldnames: Iterable[str]) -> list[str]:
    """Rename recognised columns to their canonical names; leave others alone."""
    lookup = {alias: name for name, aliases in COLUMN_ALIASES.items() for alias in aliases}
    header = []
    for raw in fieldnames:
        key = raw.strip().lower()
        header.append(lookup.get(key, key))
    for name in REQUIRED_COLUMNS:
        if header.count(name) > 1:
            raise RequestFileError(f"more than one column means {name!r}: {list(fieldnames)}", line=1)
    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        accepted = "; ".join(f"{c} ({'/'.join(COLUMN_ALIASES[c])})" for c in missing)
        raise RequestFileError(f"missing required column(s): {accepted}", line=1)
    return header


def _parse_row(row: dict[str, str], line: int, num_floors: int | None) -> Passenger:
    passenger_id = (row.get("passenger_id") or "").strip()
    if not passenger_id:
        raise RequestFileError("passenger_id is empty", line)

    time = _parse_int(row, "time", line)
    source = _parse_int(row, "source", line)
    destination = _parse_int(row, "destination", line)

    for name, floor in (("source", source), ("destination", destination)):
        if floor < 1:
            raise RequestFileError(f"{name} floor {floor} is below 1 (floors are numbered from 1)", line)
        if num_floors is not None and floor > num_floors:
            raise RequestFileError(f"{name} floor {floor} outside 1..{num_floors}", line)

    try:
        return Passenger(passenger_id, source, destination, time)
    except ValueError as e:
        raise RequestFileError(str(e), line) from e


def _parse_int(row: dict[str, str], column: str, line: int) -> int:
    raw = (row.get(column) or "").strip()
    try:
        return int(raw)
    except ValueError:
        raise RequestFileError(f"{column} must be an integer, got {raw!r}", line) from None
