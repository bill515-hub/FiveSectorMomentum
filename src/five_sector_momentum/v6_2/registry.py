from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .canonical import content_hash, file_hash


def load(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def validate(registry: dict[str, Any], v6: dict[str, Any]) -> pd.DataFrame:
    scenarios = registry.get("scenario_order", [])
    rows = []
    def check(name, expected, actual):
        rows.append({"check": name, "expected": str(expected), "actual": str(actual), "passed": expected == actual})
    check("registry_version", "1.0", str(registry.get("registry_version")))
    check("research_status", "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION", registry.get("research_status"))
    check("scenario_count", 12, len(scenarios))
    check("sequence", list(range(1, 13)), [x.get("sequence") for x in scenarios])
    check("unique_ids", 12, len({x.get("id") for x in scenarios}))
    check("strategy_count", 2, len(registry.get("strategies", [])))
    check("attempt_cap", 14, registry.get("run_budget", {}).get("global_attempt_cap"))
    check("v6_common_parameters_hash", content_hash(v6.get("common_parameters")), registry.get("inheritance", {}).get("v6_common_parameters_semantic_sha256"))
    check("same_day_range_filter", False, registry.get("causal_execution", {}).get("same_day_range_filter"))
    check("max_margin_stale_days", 5, registry.get("margin", {}).get("max_stale_trading_days"))
    return pd.DataFrame(rows)


def freeze_metadata(registry_path: Path, v6_path: Path, config_path: Path) -> dict[str, Any]:
    registry = load(registry_path)
    return {
        "registry_file_sha256": file_hash(registry_path),
        "registry_semantic_sha256": content_hash(registry),
        "canonical_v6_file_sha256": file_hash(v6_path),
        "resolved_config_file_sha256": file_hash(config_path),
        "scenario_ids": [x["id"] for x in registry["scenario_order"]],
        "locked_before_performance": True,
        "performance_results_seen_before_lock": False,
    }


def write_freeze(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

