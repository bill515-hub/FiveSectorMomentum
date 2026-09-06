from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from .canonical import content_hash, file_hash


def load(path: str | Path) -> dict[str, Any]:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _normalized(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _normalized(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_normalized(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def validate(v61: dict[str, Any], v6: dict[str, Any]) -> pd.DataFrame:
    scenarios = v61.get("scenario_order", [])
    rows = []
    def check(name: str, expected: Any, actual: Any):
        rows.append({"check": name, "expected": str(expected), "actual": str(actual), "passed": bool(expected == actual)})
    check("registry_version", "1.1", str(v61.get("registry_version")))
    check("research_status", "PROVISIONAL_DAILY_ONLY", v61.get("research_status"))
    check("scenario_count", 14, len(scenarios))
    check("sequence", list(range(1, 15)), [x.get("sequence") for x in scenarios])
    check("unique_ids", 14, len({x.get("id") for x in scenarios}))
    check("strategy_count", 2, len(v61.get("strategies", [])))
    check("attempt_cap", 16, v61.get("run_budget", {}).get("global_attempt_cap"))
    check("legacy_fee_scenarios", ["R01", "R02"], [x["id"] for x in scenarios if x.get("fee") == "legacy"])
    check("corrected_fee_scenarios", 12, sum(x.get("fee") == "corrected" for x in scenarios))
    check("common_parameter_inheritance", _normalized(v6.get("common_parameters")), _normalized(v61.get("common_parameters")))
    check("no_broker_forced_liquidation", False, v61["common_parameters"]["margin"]["broker_forced_liquidation_model_enabled"])
    return pd.DataFrame(rows)


def freeze_metadata(registry_path: Path, v6_path: Path, config_path: Path) -> dict[str, Any]:
    registry = load(registry_path)
    return {
        "registry_file_sha256": file_hash(registry_path),
        "registry_semantic_sha256": content_hash(_normalized(registry)),
        "canonical_v6_file_sha256": file_hash(v6_path),
        "resolved_config_file_sha256": file_hash(config_path),
        "scenario_ids": [x["id"] for x in registry["scenario_order"]],
        "locked_before_performance": True,
    }


def write_freeze(path: Path, metadata: dict[str, Any]) -> None:
    path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
