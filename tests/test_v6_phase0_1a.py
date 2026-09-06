from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from five_sector_momentum.v6.adapters import build_expected_artifact_inventory
from five_sector_momentum.v6.attempt_ledger import attempt_count, exclusive_lock, initialize_ledger
from five_sector_momentum.v6.canonical import canonical_dataframe_hash, canonical_json_hash, write_table_pair
from five_sector_momentum.v6.events import AccountInsolventEvent, EventReason, MarginUtilizationBreachDiagnostic
from five_sector_momentum.v6.mini_engine import (
    account_state,
    adverse_fill_price,
    calculate_exchange_fee,
    cap_target,
    causal_point_sharpe,
    limit_allows,
    matched_roll_order,
    net_targets,
    participation_fill,
    split_cross_zero,
    utilization_breach,
)
from five_sector_momentum.v6.probes import probe_ft_limit, sanitize_error
from five_sector_momentum.v6.registry import load_registry, resolved_config, validate_registry, validate_resolved_config
from five_sector_momentum.v6.secrets import scan_paths
from five_sector_momentum.v6.units import UNIT_REGISTRY, validate_units


ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml"


def test_registry_v14_exact_counts_and_margin_semantics():
    registry = load_registry(REGISTRY_PATH)
    facts = validate_registry(registry)
    assert (facts.version, facts.scenarios, facts.strategies, facts.comparisons, facts.attempt_cap) == ("1.4", 44, 22, 12, 48)
    margin = registry["common_parameters"]["margin"]
    assert margin["broker_forced_liquidation_model_enabled"] is False
    assert margin["eod_utilization_breach_action"] == "RECORD_DIAGNOSTIC_THEN_RECOMPUTE_NEXT_TARGET"


def test_resolved_config_is_registry_exact_plus_non_economic_runtime():
    registry = load_registry(REGISTRY_PATH)
    config = resolved_config(registry, REGISTRY_PATH)
    validate_resolved_config(config, registry)
    assert config["v6_runtime"]["full_history_launcher_enabled"] is False


def test_canonical_table_hash_is_row_order_invariant_when_keyed():
    a = pd.DataFrame({"key": [2, 1], "x": [1.25, np.nan]})
    b = a.iloc[::-1].reset_index(drop=True)
    assert canonical_dataframe_hash(a, ["key"]) == canonical_dataframe_hash(b, ["key"])
    b.loc[b.key == 2, "x"] = 1.26
    assert canonical_dataframe_hash(a, ["key"]) != canonical_dataframe_hash(b, ["key"])


def test_csv_pickle_pair_has_one_semantic_hash(tmp_path):
    frame = pd.DataFrame({"a": [1, 2], "b": ["甲", "乙"]})
    result = write_table_pair(frame, tmp_path / "table")
    assert Path(result["csv"]).exists() and Path(result["pickle"]).exists()
    assert canonical_dataframe_hash(pd.read_pickle(result["pickle"])) == result["content_sha256"]


def test_event_taxonomy_excludes_forced_liquidation():
    values = {x.value for x in EventReason}
    assert "MARGIN_CALL_LIQUIDATION" not in values
    assert "MARGIN_FORCED_REDUCTION" not in values
    assert EventReason.MARGIN_TARGET_REDUCTION.value == "MARGIN_TARGET_REDUCTION"
    assert AccountInsolventEvent("2020-01-01", -1).state == "ACCOUNT_INSOLVENT"


def test_margin_caps_are_target_only_and_breach_is_diagnostic():
    assert cap_target(100, [80, 70]) == 70
    assert cap_target(-100, [80, 70]) == -70
    event = utilization_breach(0.66, 0.79)
    assert event["recompute_next_standard_target"] is True
    assert event["action_is_forced_liquidation"] is False
    assert account_state(0) == "ACCOUNT_INSOLVENT"
    assert account_state(1) == "ACTIVE"


def test_fee_trade_types_and_cross_zero_hand_calculation():
    legs = split_cross_zero(position=3, order=-5)
    assert [(x.trade_type, x.lots) for x in legs] == [("CLOSE_YESTERDAY", 3), ("OPEN", 2)]
    fee = calculate_exchange_fee(trade_type="OPEN", lots=2, price=4000, multiplier=10, fixed_per_lot=1, rate=0.0001, customer_multiplier=1.5)
    assert fee == pytest.approx(15.0)


def test_integer_tick_and_directional_limit_hand_cases():
    assert adverse_fill_price(100, 2, 0.5, 1) == 101
    assert adverse_fill_price(100, 2, 0.5, -1) == 99
    with pytest.raises(ValueError):
        adverse_fill_price(100, 0.5, 1, 1)
    assert not limit_allows(1, 110, 110, 90)
    assert limit_allows(-1, 109, 110, 90)
    assert not limit_allows(-1, 90, 110, 90)


def test_partial_fill_roll_and_sleeve_netting_once():
    assert participation_fill(800, volume=10000, fraction=0.05) == (500, 300)
    assert matched_roll_order(3, -2) == [("CLOSE_OLD", -3), ("OPEN_NEW", -2)]
    assert net_targets([("RB", 5), ("RB", -3), ("T", 2)]) == {"RB": 2, "T": 2}


def test_point_sharpe_prefix_is_future_invariant_and_no_backfill():
    base = pd.Series(np.linspace(100, 150, 80))
    extended = pd.concat([base, pd.Series([10000, -10000])], ignore_index=True)
    original = causal_point_sharpe(base, 20, 5)
    future = causal_point_sharpe(extended, 20, 5).iloc[: len(base)]
    pd.testing.assert_series_equal(original, future, check_names=False)
    assert original.iloc[:25].isna().all()


def test_unit_registry_preserves_point_signal_and_integer_lots():
    validate_units()
    assert UNIT_REGISTRY["raw_price"] == "price_points"
    assert UNIT_REGISTRY["position"] == "integer_lots"


class _FakePro:
    def __init__(self, mode):
        self.mode = mode

    def ft_limit(self, **kwargs):
        if self.mode == "data":
            return pd.DataFrame({"ts_code": [kwargs["ts_code"]], "trade_date": ["20260101"], "up_limit": [100], "down_limit": [80]})
        if self.mode == "empty":
            return pd.DataFrame()
        if self.mode == "permission":
            raise RuntimeError("抱歉，您没有权限")
        raise ConnectionError("endpoint timeout")


@pytest.mark.parametrize("mode,expected", [("data", "DATA"), ("empty", "SILENT_EMPTY"), ("permission", "NO_PERMISSION"), ("error", "ENDPOINT_UNAVAILABLE")])
def test_limit_probe_classifies_endpoint_states(tmp_path, mode, expected):
    contracts = pd.DataFrame([{"exchange": "SHFE", "contract_role": "active", "ts_code": "RB2609.SHF", "instrument": "RB", "list_date": "20250901", "delist_date": "20260915"}])
    result, _ = probe_ft_limit(_FakePro(mode), contracts, tmp_path)
    assert result.iloc[0].classification == expected


def test_error_sanitization_never_returns_long_secret_like_value():
    classification, error_class, fingerprint = sanitize_error(RuntimeError("token ABCDEFGHIJKLMNOPQRSTUVWXYZ123456 has no permission"))
    assert "ABC" not in fingerprint
    assert len(fingerprint) == 16


def test_expected_artifact_inventory_has_core_evidence():
    inventory = build_expected_artifact_inventory(ROOT)
    core = inventory[inventory.requirement == "CORE"]
    assert len(core) == 20
    assert not (core.status == "BLOCKER_MISSING_CORE").any()
    assert set(inventory.loc[~inventory.exists.astype(bool) & (inventory.requirement == "SUPPORTING"), "status"]) <= {"NOT_APPLICABLE"}


def test_attempt_ledger_probe_path_does_not_increment(tmp_path):
    ledger = tmp_path / "ledger.csv"
    initialize_ledger(ledger)
    before = attempt_count(ledger)
    with exclusive_lock(tmp_path / "lock"):
        canonical_json_hash({"probe": True})
    assert attempt_count(ledger) == before == 0


def test_secret_scanner_reports_without_copying_value(tmp_path, monkeypatch):
    value = "TEST_ONLY_TOKEN_1234567890"
    monkeypatch.setenv("TUSHARE_TOKEN", value)
    path = tmp_path / "bad.txt"
    path.write_text("tushare_token=TEST_ONLY_TOKEN_1234567890", encoding="utf-8")
    findings = scan_paths([tmp_path])
    assert not findings.empty
    assert value not in findings.to_string()
