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
    checks = {
        "registry_version": registry.get("registry_version") == "1.0_FINAL",
        "registry_locked": registry.get("registry_status") == "LOCKED_BEFORE_PERFORMANCE",
        "scenario_count": len(scenarios) == 17,
        "sequence": [x.get("sequence") for x in scenarios] == list(range(1, 18)),
        "scenario_ids": [x.get("id") for x in scenarios] == EXPECTED_IDS,
        "attempt_cap": registry.get("run_budget", {}).get("global_attempt_cap") == 19,
        "bootstrap_members": registry.get("statistics", {}).get("bootstrap_members") == BOOTSTRAP_MEMBERS,
        "mapping_rule": registry.get("mapping_correction", {}).get("rule") == "causal_hold_last_accepted_contract_when_proposed_expiry_moves_backward",
        "mapping_no_future": registry.get("mapping_correction", {}).get("future_lookahead_allowed") is False,
        "legacy_exact_reproduction_disabled": registry.get("baseline", {}).get("exact_legacy_reproduction_required") is False,
        "same_day_range_filter": registry.get("execution", {}).get("same_day_range_filter") is False,
        "next_close_complete_settlement": registry.get("execution", {}).get("next_close_complete_daily_settlement") is True,
    }
    return pd.DataFrame([{"check": key, "passed": value} for key, value in checks.items()])


def bundle_hash(rows: list[dict[str, str]]) -> str:
    return content_hash(sorted(rows, key=lambda x: x["path"]))


def freeze_metadata(registry_path: Path, config_path: Path,
                    source_paths: list[Path], input_paths: list[Path]) -> dict[str, Any]:
    source_rows = [{"path": path.relative_to(registry_path.parents[2]).as_posix(), "sha256": file_hash(path)} for path in sorted(source_paths)]
    input_rows = [{"path": path.relative_to(registry_path.parents[2]).as_posix(), "sha256": file_hash(path)} for path in sorted(input_paths)]
    registry = load(registry_path)
    return {
        "registry_file_sha256": file_hash(registry_path),
        "registry_semantic_sha256": content_hash(registry),
        "resolved_config_file_sha256": file_hash(config_path),
        "source_hashes": source_rows,
        "input_hashes": input_rows,
        "source_bundle_sha256": bundle_hash(source_rows),
        "input_bundle_sha256": bundle_hash(input_rows),
        "scenario_ids": [x["id"] for x in registry["scenario_order"]],
        "locked_before_performance": True,
        "performance_results_seen_before_lock": False,
    }


def write_freeze(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

