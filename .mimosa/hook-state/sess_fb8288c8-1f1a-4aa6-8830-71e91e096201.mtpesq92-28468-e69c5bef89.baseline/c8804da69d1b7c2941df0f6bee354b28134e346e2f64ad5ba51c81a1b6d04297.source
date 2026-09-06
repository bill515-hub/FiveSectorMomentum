from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .canonical import canonical_json_hash, sha256_file


class RegistryValidationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RegistryFacts:
    version: str
    scenarios: int
    strategies: int
    comparisons: int
    attempt_cap: int
    semantic_hash: str


def load_registry(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = yaml.safe_load(handle)
    if not isinstance(value, dict):
        raise RegistryValidationError("Machine registry must be a mapping")
    return value


def validate_registry(registry: dict[str, Any]) -> RegistryFacts:
    errors: list[str] = []
    scenarios = registry.get("scenario_order", [])
    strategies = registry.get("base_strategy_family", [])
    comparisons = registry.get("single_factor_comparisons", [])
    budget = registry.get("run_budget", {})
    if str(registry.get("registry_version")) != "1.4":
        errors.append("registry_version must equal 1.4")
    if len(scenarios) != 44:
        errors.append(f"scenario count {len(scenarios)} != 44")
    if len(strategies) != 22:
        errors.append(f"base strategy count {len(strategies)} != 22")
    if len(comparisons) != 12:
        errors.append(f"comparison edge count {len(comparisons)} != 12")
    if budget.get("global_attempt_cap") != 48:
        errors.append("global attempt cap must equal 48")
    if budget.get("registered_effective_runs") != 44:
        errors.append("registered effective runs must equal 44")
    ids = [row.get("id") for row in scenarios]
    sequences = [row.get("sequence") for row in scenarios]
    if len(set(ids)) != len(ids):
        errors.append("scenario IDs are not unique")
    if sequences != list(range(1, 45)):
        errors.append("scenario sequence must be exactly 1..44")
    provider_ids = {row.get("provider_scenario") for row in strategies}
    if not provider_ids.issubset(set(ids)):
        errors.append(f"unknown provider scenarios: {sorted(provider_ids - set(ids))}")
    margin = registry.get("common_parameters", {}).get("margin", {})
    required_margin = {
        "utilization_caps_are_target_constraints": True,
        "broker_forced_liquidation_model_enabled": False,
        "eod_utilization_breach_action": "RECORD_DIAGNOSTIC_THEN_RECOMPUTE_NEXT_TARGET",
        "insolvency_state": "ACCOUNT_INSOLVENT",
        "synthetic_limited_liability_return_curve_forbidden": True,
    }
    for key, expected in required_margin.items():
        if margin.get(key) != expected:
            errors.append(f"margin.{key} != {expected!r}")
    if errors:
        raise RegistryValidationError("; ".join(errors))
    return RegistryFacts(
        version="1.4",
        scenarios=len(scenarios),
        strategies=len(strategies),
        comparisons=len(comparisons),
        attempt_cap=int(budget["global_attempt_cap"]),
        semantic_hash=canonical_json_hash(registry),
    )


def resolved_config(registry: dict[str, Any], registry_path: Path) -> dict[str, Any]:
    validate_registry(registry)
    config = copy.deepcopy(registry)
    config["v6_runtime"] = {
        "scope": "PHASE0_AND_PHASE1A_ONLY",
        "full_history_launcher_enabled": False,
        "full_history_attempts_consumed": 0,
        "machine_registry_path": str(registry_path.resolve()),
        "machine_registry_file_sha256": sha256_file(registry_path),
        "resolved_config_policy": "generated_or_exactly_validated_from_machine_registry",
        "secret_source": "PROJECT_EXISTING_SECURE_ENVIRONMENT",
        "secret_values_in_config_forbidden": True,
    }
    return config


def validate_resolved_config(config: dict[str, Any], registry: dict[str, Any]) -> None:
    runtime = config.get("v6_runtime")
    if not isinstance(runtime, dict) or runtime.get("full_history_launcher_enabled") is not False:
        raise RegistryValidationError("v6_runtime must disable the full-history launcher")
    payload = {k: v for k, v in config.items() if k != "v6_runtime"}
    if canonical_json_hash(payload) != canonical_json_hash(registry):
        raise RegistryValidationError("resolved config economic/registry fields differ from machine registry")

