from __future__ import annotations

import csv
import os
from contextlib import contextmanager
from pathlib import Path


HEADERS = ["attempt_id", "scenario_id", "started_at", "status", "process_id", "note"]


def initialize_ledger(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8") as handle:
            csv.writer(handle).writerow(HEADERS)


def attempt_count(path: Path) -> int:
    initialize_ledger(path)
    with path.open("r", newline="", encoding="utf-8") as handle:
        return max(0, sum(1 for _ in csv.reader(handle)) - 1)


@contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = None
    try:
        descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if path.exists():
            path.unlink()

