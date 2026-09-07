from __future__ import annotations

import unittest
from pathlib import Path
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.v6_3a_independent_audit_v2 import (  # noqa: E402
    BASE_CONFIG, FREEZE_PATH, STRATEGIES, aggregate_returns, drawdown_stats, sha256,
)


class IndependentAuditMetricTests(unittest.TestCase):
    def test_monthly_returns_are_compounded_not_summed(self):
        idx = pd.to_datetime(["2020-01-02", "2020-01-03", "2020-02-03"])
        r = pd.Series([0.10, -0.10, 0.05], index=idx)
        result = aggregate_returns(r, "monthly")
        self.assertAlmostEqual(result.loc["2020-01"], -0.01, places=12)
        self.assertAlmostEqual(result.loc["2020-02"], 0.05, places=12)

    def test_average_drawdown_includes_zero_peak_days(self):
        idx = pd.date_range("2020-01-01", periods=3)
        stats = drawdown_stats(pd.Series([0.10, -0.10, 1 / 9], index=idx))
        self.assertAlmostEqual(stats["average_drawdown"], -1 / 30, places=12)
        self.assertAlmostEqual(stats["maximum_drawdown"], -0.10, places=12)

    def test_strategy_catalog_uses_human_readable_descriptions(self):
        self.assertEqual(set(STRATEGIES), {"G01", "G02", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "D01", "D02", "T01", "T02", "T03", "N01", "N02", "T04"})
        self.assertTrue(all(len(x["description"]) > 25 for x in STRATEGIES.values()))

    def test_original_freeze_omits_actual_base_config(self):
        text = FREEZE_PATH.read_text(encoding="utf-8")
        self.assertNotIn("configs/five_sector_momentum_v4_2_repaired.yaml", text)
        self.assertEqual(sha256(BASE_CONFIG), "45c373b25c49d742a44ccbc971dd703a89b7926ca0faeb3ed819e65fef7030bd")

    def test_carver_normal_tail_ratio_is_near_one(self):
        rng = np.random.default_rng(20260907)
        x = rng.normal(size=1_000_000)
        x = x - x.mean()
        q01, q30, q70, q99 = np.quantile(x, [0.01, 0.30, 0.70, 0.99])
        self.assertAlmostEqual((q01 / q30) / 4.43, 1.0, delta=0.02)
        self.assertAlmostEqual((q99 / q70) / 4.43, 1.0, delta=0.02)


if __name__ == "__main__":
    unittest.main()
