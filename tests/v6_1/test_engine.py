from __future__ import annotations

import unittest

import pandas as pd

from five_sector_momentum.v6_1.engine import ScenarioV61, _ExecutionProxyMixin, corrected_fee_schedule


def rules():
    rows = []
    for instrument, contract, per_lot, rate in [("RB", "RB2401.SHF", 0.0, 0.0001), ("T", "T2403.CFX", 3.0, 0.0)]:
        for trade_type in ["open", "close_non_today", "close_today"]:
            rows.append({"rule_id": f"{instrument}-{trade_type}", "contract": contract, "instrument": instrument, "effective_from": "2020-01-01", "effective_to": "2030-01-01", "trade_type": trade_type, "fee_per_lot": 0.0 if instrument == "T" and trade_type == "close_today" else per_lot, "fee_rate": rate, "fee_rate_unit": "legacy", "source_type": "test", "source_url": "test", "is_proxy": trade_type == "close_today"})
    return pd.DataFrame(rows)


class Dummy(_ExecutionProxyMixin):
    pass


class EnginePolicyTests(unittest.TestCase):
    def setUp(self):
        self.engine = Dummy()

    def reason(self, policy, quantity, price, pre, volume=100):
        self.engine.v61_scenario = ScenarioV61("X", "s", policy, "normal", "vendor_open", "corrected")
        bar = pd.Series({"high": price, "low": price, "pre_settle": pre, "volume": volume})
        order = type("O", (), {"quantity": quantity})()
        return self.engine._proxy_rejection(pd.Timestamp("2024-01-02"), order, bar)

    def test_p0_never_rejects_one_price_by_direction(self):
        self.assertIsNone(self.reason("p0", 1, 110, 100))

    def test_p1_directional_policy(self):
        self.assertEqual(self.reason("p1", 1, 110, 100), "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT")
        self.assertIsNone(self.reason("p1", -1, 110, 100))
        self.assertEqual(self.reason("p1", -1, 90, 100), "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT")
        self.assertIsNone(self.reason("p1", 1, 90, 100))

    def test_p1_unknown_and_zero_volume_reject_both(self):
        self.assertEqual(self.reason("p1", 1, 100, 100), "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT")
        self.assertEqual(self.reason("p1", -1, 110, float("nan")), "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT")
        self.assertEqual(self.reason("p1", -1, 110, 100, 0), "DAILY_ONE_PRICE_DIRECTIONAL_PROXY_REJECT")

    def test_p2_rejects_both(self):
        self.assertEqual(self.reason("p2", 1, 110, 100), "DAILY_ONE_PRICE_ALL_SIDE_STRESS_REJECT")
        self.assertEqual(self.reason("p2", -1, 110, 100), "DAILY_ONE_PRICE_ALL_SIDE_STRESS_REJECT")

    def test_corrected_proportional_fee_and_fixed_t(self):
        fee = corrected_fee_schedule(rules())
        rb = fee.charge("RB2401.SHF", "RB", pd.Timestamp("2024-01-02"), "open", 2, 3500, 10, 1.5)
        self.assertAlmostEqual(rb.fee_rate, 0.001)
        self.assertAlmostEqual(rb.exchange_fee, 70.0)
        self.assertAlmostEqual(rb.client_fee, 105.0)
        t_open = fee.charge("T2403.CFX", "T", pd.Timestamp("2024-01-02"), "open", 2, 102, 10000, 1.5)
        t_today = fee.charge("T2403.CFX", "T", pd.Timestamp("2024-01-02"), "close_today", 2, 102, 10000, 1.5)
        self.assertAlmostEqual(t_open.exchange_fee, 6.0)
        self.assertAlmostEqual(t_today.exchange_fee, 0.0)

    def test_cost_spec_integer_ticks(self):
        self.assertEqual(ScenarioV61("x", "s", "p1", "fixed_1_tick", "vendor_open", "corrected").cost().fixed_ticks, 1)
        self.assertEqual(ScenarioV61("x", "s", "p1", "fixed_3_tick", "vendor_open", "corrected").cost().fixed_ticks, 3)


if __name__ == "__main__":
    unittest.main()
