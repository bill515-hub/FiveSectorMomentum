from __future__ import annotations

import contextlib
import csv
import os
from datetime import datetime
from pathlib import Path

HEADER = ["attempt", "scenario_id", "sequence", "status", "started_at", "finished_at", "output_dir", "registry_sha256", "message_code"]


def initialize(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        with path.open("w", newline="", encoding="utf-8-sig") as handle:
            csv.writer(handle).writerow(HEADER)


def rows(path: Path) -> list[dict[str, str]]:
    initialize(path)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


@contextlib.contextmanager
def exclusive_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        yield
    finally:
        os.close(descriptor)
        path.unlink(missing_ok=True)


def start(path: Path, scenario_id: str, sequence: int, output_dir: Path, registry_sha256: str, cap: int = 14) -> int:
    prior = rows(path)
    if len(prior) >= cap:
        raise RuntimeError("V6_2_ATTEMPT_CAP_EXCEEDED")
    if any(row["status"] == "STARTED" for row in prior):
        raise RuntimeError("V6_2_UNFINISHED_ATTEMPT_EXISTS")
    completed = [row for row in prior if row["status"] == "COMPLETED"]
    expected_sequence = len(completed) + 1
    if int(sequence) != expected_sequence:
        raise RuntimeError(f"V6_2_SEQUENCE_VIOLATION_EXPECTED_{expected_sequence}_GOT_{sequence}")
    if scenario_id in {row["scenario_id"] for row in completed}:
        raise RuntimeError("V6_2_COMPLETED_SCENARIO_RERUN_FORBIDDEN")
    attempt = len(prior) + 1
    with path.open("a", newline="", encoding="utf-8-sig") as handle:
        csv.writer(handle).writerow([attempt, scenario_id, sequence, "STARTED", datetime.now().isoformat(), "", str(output_dir.resolve()), registry_sha256, ""])
    return attempt


def finish(path: Path, attempt: int, status: str, message_code: str = "") -> None:
    current = rows(path)
    if not current or int(current[-1]["attempt"]) != attempt:
        raise RuntimeError("V6_2_ATTEMPT_LEDGER_APPEND_ORDER_VIOLATION")
    current[-1]["status"] = status
    current[-1]["finished_at"] = datetime.now().isoformat()
    current[-1]["message_code"] = message_code
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADER)
        writer.writeheader()
        writer.writerows(current)
