from __future__ import annotations

from copy import deepcopy
import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.engine_v3 import PendingOrderV3
from five_sector_momentum.v6_2.canonical import file_hash
from five_sector_momentum.v6_2.engine import BacktestEngineV62, ScenarioV62
from five_sector_momentum.v6_2.margin import FALLBACK_SOURCE, LaggedMarginTable, VENDOR_SOURCE
from five_sector_momentum.v6_2.registry import load, validate
from five_sector_momentum.v6_2.attempts import finish as finish_attempt, start as start_attempt
from five_sector_momentum.v6_2.workflow import _post_trade_shape_diagnostics


ROOT = Path(__file__).resolve().parents[2]


class DummyFee:
    def charge(self, contract, instrument, date, trade_type, lots, price, point_value, multiplier):
        return SimpleNamespace(exchange_fee=2.0 * lots, client_fee=3.0 * lots,
            fee_per_lot=2.0, fee_rate=0.0, rule_id="HAND", source_type="HAND", source_url="", is_proxy=True)


def mini_engine(scenario: ScenarioV62, high=110.0, low=90.0, close=105.0, settlement=104.0, volume=999999, oi=999999):
    engine = BacktestEngineV62.__new__(BacktestEngineV62)
    date = pd.Timestamp("2024-01-03")
    contract = "RB2405.SHF"
    engine.v62_scenario = scenario
    engine._cost = scenario.cost()
    engine.bars = pd.DataFrame([{
        "date": date, "contract": contract, "open": 100.0, "high": high, "low": low,
        "close": close, "settlement": settlement, "volume": volume, "open_interest": oi,
        "tick_size": 1.0, "point_value": 10.0,
    }]).set_index(["date", "contract"])
    engine.liquidity = {(pd.Timestamp("2024-01-02"), "RB"): {"median_volume": 1000.0, "median_open_interest": 5000.0}}
    engine.execution = {"max_volume_participation": 0.05, "fallback_executable_volume": 10000,
        "roll_extra_ticks": 1.0, "high_liquidity_instruments": ["T", "RB", "AL"],
        "high_liquidity_min_median_volume": 10000, "high_liquidity_min_median_open_interest": 20000}
    engine.fee_schedule = DummyFee()
    engine.contract_meta = pd.DataFrame({"instrument": ["RB"]}, index=[contract])
    engine.sector_by_instrument = {"RB": "ferrous"}
    return engine, date, contract


def execute(engine, date, contract, quantity=10, reason="normal_rebalance"):
    order = PendingOrderV3(contract, "RB", quantity, pd.Timestamp("2024-01-02"), reason)
    return engine._execute_order_v3(date, order, engine.v62_scenario.legacy_scenario().execution(), {})


class RegistryAndScopeTests(unittest.TestCase):
    def test_registry_counts_hash_and_freeze(self):
        registry_path = ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_MACHINE_REGISTRY.yaml"
        v6_path = ROOT / "docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml"
        registry, v6 = load(registry_path), load(v6_path)
        self.assertTrue(validate(registry, v6).passed.all())
        freeze = json.loads((ROOT / "docs/v6_2_causal_daily_only_correction_plan/V6_2_REGISTRY_FREEZE.json").read_text(encoding="utf-8"))
        self.assertEqual(file_hash(registry_path), freeze["registry_file_sha256"])
        self.assertTrue(freeze["locked_before_performance"])

    def test_protected_legacy_hashes(self):
        audit = pd.read_csv(ROOT / "data/v6_2/legacy_hash_verification.csv")
        for row in audit.to_dict("records"):
            self.assertEqual(file_hash(ROOT / row["path"]), row["expected_sha256"])

    def test_execution_source_has_no_same_day_range_or_final_capacity_access(self):
        source = inspect.getsource(BacktestEngineV62._execute_order_v3)
        for forbidden in ['bar.get("high"', 'bar.get("low"', 'bar.get("settlement"', 'bar.get("volume"', 'bar.get("open_interest"']:
            self.assertNotIn(forbidden, source)
        self.assertIn("order.created_date", source)

    def test_challenge_set_is_concrete_and_not_truth(self):
        frame = pd.read_pickle(ROOT / "data/v6_2/one_price_shape_challenge_set.pkl")
        self.assertEqual(len(frame), 13)
        self.assertEqual(frame.date.notna().sum(), 13)
        self.assertTrue((~frame.official_limit_truth).all())
        self.assertTrue(frame.proxy_not_truth.all())
        self.assertEqual(int(frame.contract.eq("RU2505.SHF").sum()), 1)

    def test_production_bar_ts_code_is_normalized_only_for_post_trade_diagnostic(self):
        data = SimpleNamespace(bars=pd.DataFrame([{
            "date": pd.Timestamp("2025-04-07"), "ts_code": "RU2505.SHF",
            "high": 15000.0, "low": 15000.0, "pre_settle": 16000.0,
        }]))
        result = SimpleNamespace(
            fills=pd.DataFrame([{"date": pd.Timestamp("2025-04-07"), "created_date": pd.Timestamp("2025-04-03"),
                "contract": "RU2505.SHF", "instrument": "RU", "quantity": -1, "reason": "roll"}]),
            rejections=pd.DataFrame(),
        )
        rows = _post_trade_shape_diagnostics(result, data, "X")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows.iloc[0].contract, "RU2505.SHF")
        self.assertEqual(rows.iloc[0].classification, "POST_TRADE_ONE_PRICE_SHAPE_NOT_LIMIT_TRUTH")

    def test_attempt_failed_retry_and_sequence_are_independent(self):
        with TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.csv"
            out = Path(folder) / "out"
            first = start_attempt(ledger, "R01", 1, out, "HASH", 14)
            finish_attempt(ledger, first, "FAILED", "TEST")
            second = start_attempt(ledger, "R01", 1, out, "HASH", 14)
            finish_attempt(ledger, second, "COMPLETED")
            third = start_attempt(ledger, "R02", 2, out, "HASH", 14)
            finish_attempt(ledger, third, "COMPLETED")
            self.assertEqual([first, second, third], [1, 2, 3])
            with self.assertRaisesRegex(RuntimeError, "SEQUENCE_VIOLATION"):
                start_attempt(ledger, "B02", 4, out, "HASH", 14)

    def test_completed_scenario_cannot_be_retried(self):
        with TemporaryDirectory() as folder:
            ledger = Path(folder) / "ledger.csv"
            out = Path(folder) / "out"
            attempt = start_attempt(ledger, "R01", 1, out, "HASH", 14)
            finish_attempt(ledger, attempt, "COMPLETED")
            with self.assertRaisesRegex(RuntimeError, "COMPLETED_SCENARIO"):
                start_attempt(ledger, "R01", 2, out, "HASH", 14)


class CausalExecutionHandTests(unittest.TestCase):
    def test_high_low_close_settlement_final_volume_oi_do_not_change_open_fill(self):
        scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", "normal")
        e1, d1, c1 = mini_engine(scenario, 100.0, 100.0, -999.0, -998.0, 0, 0)
        e2, d2, c2 = mini_engine(scenario, 100000.0, -100000.0, 999.0, 998.0, 10**9, 10**9)
        a = execute(e1, d1, c1)[0]
        b = execute(e2, d2, c2)[0]
        cols = ["quantity", "price", "reference_price", "cash_slippage_cost", "total_slippage_ticks", "participation_rate"]
        pd.testing.assert_frame_equal(pd.DataFrame(a)[cols], pd.DataFrame(b)[cols])

    def test_tick_sensitivity_does_not_change_eligibility_or_quantity(self):
        outputs = []
        for slip in ["fixed_1_tick", "fixed_3_tick"]:
            scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", slip)
            engine, date, contract = mini_engine(scenario)
            fills, remainder, rejection = execute(engine, date, contract, 80)
            outputs.append((sum(x["quantity"] for x in fills), remainder, rejection, sum(x["cash_slippage_cost"] for x in fills)))
        self.assertEqual(outputs[0][:3], outputs[1][:3])
        self.assertGreater(outputs[1][3], outputs[0][3])

    def test_cash_slippage_hand_formula_and_unique_columns(self):
        scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", "fixed_3_tick")
        engine, date, contract = mini_engine(scenario)
        fills, remainder, rejection = execute(engine, date, contract, 10, "roll")
        self.assertIsNone(rejection); self.assertEqual(remainder, 0)
        self.assertAlmostEqual(sum(x["cash_slippage_cost"] for x in fills), 10 * 4 * 1 * 10)
        self.assertTrue(all(x["embedded_slippage_cost"] == 0 for x in fills))
        self.assertTrue(all(x["price"] == x["reference_price"] == 100 for x in fills))

    def test_partial_fill_uses_only_lagged_capacity(self):
        scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", "normal")
        engine, date, contract = mini_engine(scenario, volume=0)
        fills, remainder, rejection = execute(engine, date, contract, 80)
        self.assertEqual(sum(x["quantity"] for x in fills), 50)
        self.assertEqual(remainder, 30)
        self.assertEqual(rejection["reason"], "partial_fill")

    def test_open_and_close_new_position_pnl_boundary(self):
        open_scenario = ScenarioV62("O", "reference_v3_252", "vendor_open", "static_fallback", "fixed_1_tick")
        close_scenario = ScenarioV62("C", "reference_v3_252", "next_close", "static_fallback", "fixed_1_tick")
        eo, date, contract = mini_engine(open_scenario, close=110, settlement=110)
        ec, _, _ = mini_engine(close_scenario, close=110, settlement=110)
        fo = execute(eo, date, contract, 1)[0]
        fc = execute(ec, date, contract, 1)[0]
        gross_open, cost_open, _, _ = eo._mark_to_market(date, {}, fo, {})
        gross_close, cost_close, _, _ = ec._mark_to_market(date, {}, fc, {})
        self.assertEqual(gross_open, 100.0)
        self.assertEqual(gross_close, 0.0)
        self.assertEqual(cost_open, cost_close)

    def test_open_cash_cost_equals_linear_adverse_price_algebra(self):
        scenario = ScenarioV62("X", "reference_v3_252", "vendor_open", "static_fallback", "fixed_1_tick")
        engine, date, contract = mini_engine(scenario, settlement=110)
        fills = execute(engine, date, contract, 7)[0]
        gross, costs, _, _ = engine._mark_to_market(date, {}, fills, {})
        net_cash = gross - costs
        commission = sum(x["commission"] for x in fills)
        adverse_price_net = 7 * (110 - 101) * 10 - commission
        self.assertAlmostEqual(net_cash, adverse_price_net)


class MarginAsOfTests(unittest.TestCase):
    def setUp(self):
        self.dates = pd.bdate_range("2024-01-01", "2024-01-12")
        self.table = pd.DataFrame([
            {"date": pd.Timestamp("2024-01-02"), "ts_code": "X2405.SHF", "long_margin_rate_decimal": .10,
             "short_margin_rate_decimal": .12, "known_at": pd.Timestamp("2024-01-03"), "unit_rule_id": "U"},
            {"date": pd.Timestamp("2024-01-04"), "ts_code": "X2405.SHF", "long_margin_rate_decimal": .20,
             "short_margin_rate_decimal": .22, "known_at": pd.Timestamp("2024-01-05"), "unit_rule_id": "U"},
        ])

    def test_at_least_one_trading_day_lag(self):
        table = LaggedMarginTable(self.table, self.dates, 5)
        value = table.lookup("2024-01-04", "X2405.SHF", 1, .08)
        self.assertEqual(value.rate_date, pd.Timestamp("2024-01-02"))
        self.assertEqual(value.vendor_rate, .10)

    def test_direction_specific_rate(self):
        table = LaggedMarginTable(self.table, self.dates, 5)
        self.assertEqual(table.lookup("2024-01-05", "X2405.SHF", 1, .08).vendor_rate, .20)
        self.assertEqual(table.lookup("2024-01-05", "X2405.SHF", -1, .08).vendor_rate, .22)

    def test_static_floor_and_source(self):
        table = LaggedMarginTable(self.table, self.dates, 5)
        value = table.lookup("2024-01-05", "X2405.SHF", 1, .25)
        self.assertEqual(value.effective_rate, .25)
        self.assertEqual(value.source_code, VENDOR_SOURCE)
        self.assertFalse(value.vendor_binding)

    def test_stale_and_missing_fallback(self):
        table = LaggedMarginTable(self.table, self.dates, 1)
        self.assertEqual(table.lookup("2024-01-10", "X2405.SHF", 1, .18).source_code, FALLBACK_SOURCE)
        self.assertEqual(table.lookup("2024-01-05", "Y2405.SHF", 1, .18).source_code, FALLBACK_SOURCE)

    def test_future_append_does_not_change_past_lookup(self):
        a = LaggedMarginTable(self.table.iloc[:1], self.dates, 5).lookup("2024-01-04", "X2405.SHF", 1, .08)
        b = LaggedMarginTable(self.table, self.dates, 5).lookup("2024-01-04", "X2405.SHF", 1, .08)
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main(verbosity=2)
