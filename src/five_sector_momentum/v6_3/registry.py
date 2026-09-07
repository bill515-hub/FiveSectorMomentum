from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .canonical import content_hash, file_hash


EXPECTED_IDS = [
    "G01", "G02", "S01", "S02", "S03", "S04", "S05", "S06", "S07",
    "D01", "D02", "T01", "T02", "T03", "N01", "N02", "T04",
]
BOOTSTRAP_MEMBERS = [
    "G01", "G02", "S01", "S02", "S03", "S04", "S05", "S06", "S07",
    "D01", "D02", "T01",
]


def load(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate(registry: dict[str, Any]) -> pd.DataFrame:
    scenarios = registry.get("scenario_order", [])
    rows: list[dict[str, Any]] = []

    def check(name: str, expected: Any, actual: Any) -> None:
        rows.append({"check": name, "expected": str(expected), "actual": str(actual), "passed": expected == actual})

    check("registry_version", "1.1_FINAL", str(registry.get("registry_version")))
    check("research_status", "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION", registry.get("research_status"))
    check("scenario_count", 17, len(scenarios))
    check("sequence", list(range(1, 18)), [x.get("sequence") for x in scenarios])
    check("scenario_ids", EXPECTED_IDS, [x.get("id") for x in scenarios])
    check("unique_ids", 17, len({x.get("id") for x in scenarios}))
    check("attempt_cap", 19, registry.get("run_budget", {}).get("global_attempt_cap"))
    check("bootstrap_members", BOOTSTRAP_MEMBERS, registry.get("statistics", {}).get("bootstrap_members"))
    check("bootstrap_primary_block", 20, registry.get("statistics", {}).get("primary_block_length"))
    check("bootstrap_repetitions", 5000, registry.get("statistics", {}).get("repetitions"))
    check("same_day_range_filter", False, registry.get("execution", {}).get("same_day_range_filter"))
    check("next_close_opening_only", True, registry.get("execution", {}).get("next_close_opening_segment_only"))
    return pd.DataFrame(rows)


def source_bundle_hash(entries: list[dict[str, str]]) -> str:
    return content_hash(sorted(entries, key=lambda x: x["path"]))


def freeze_metadata(
    registry_path: Path, config_path: Path, source_paths: list[Path], input_paths: list[Path],
) -> dict[str, Any]:
    source_rows = [{"path": path.as_posix(), "sha256": file_hash(path)} for path in sorted(source_paths)]
    input_rows = [{"path": path.as_posix(), "sha256": file_hash(path)} for path in sorted(input_paths)]
    registry = load(registry_path)
    return {
        "registry_file_sha256": file_hash(registry_path),
        "registry_semantic_sha256": content_hash(registry),
        "resolved_config_file_sha256": file_hash(config_path),
        "source_hashes": source_rows,
        "input_hashes": input_rows,
        "source_bundle_sha256": source_bundle_hash(source_rows),
        "input_bundle_sha256": source_bundle_hash(input_rows),
        "scenario_ids": [x["id"] for x in registry["scenario_order"]],
        "locked_before_performance": True,
        "performance_results_seen_before_lock": False,
    }


def write_freeze(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
