from __future__ import annotations

import unittest
from pathlib import Path

from five_sector_momentum.v6_1.registry import load, validate


ROOT = Path(__file__).resolve().parents[2]


class RegistryTests(unittest.TestCase):
    def test_registry_14_2_16_and_inheritance(self):
        v61 = load(ROOT / "docs/v6_1_daily_only_provisional_plan/V6_1_MACHINE_REGISTRY.yaml")
        v6 = load(ROOT / "docs/v6_20260905_research_and_test_plan/V6_MACHINE_REGISTRY.yaml")
        result = validate(v61, v6)
        self.assertTrue(result.passed.all(), result[~result.passed].to_dict("records"))


if __name__ == "__main__":
    unittest.main()
