from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd

from five_sector_momentum.settings import Settings
from five_sector_momentum.v6_3a.data import (
    build_corrected_bundle, expiry_transition_audit, prefix_invariance_check,
)
from five_sector_momentum.v6_3a.registry import load, validate


ROOT=Path(__file__).resolve().parents[2]


class TestV63A(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.settings=Settings.load(ROOT/"configs/five_sector_momentum_v4_2_repaired.yaml")
        cls.bundle,cls.diag=build_corrected_bundle(cls.settings,persist=False)

    def test_registry(self):
        checks=validate(load(ROOT/"docs/v6_3a_corrected_mapping_research/V6_3A_MACHINE_REGISTRY.yaml"))
        self.assertTrue(checks.passed.all(),checks.to_dict("records"))

    def test_backward_expiry_removed(self):
        self.assertTrue(expiry_transition_audit(self.bundle.mapping,self.bundle.contract_meta).empty)

    def test_only_sc_is_changed(self):
        self.assertEqual(set(self.diag["mapping_events"].instrument),{"SC"})
        self.assertGreater(len(self.diag["mapping_events"]),2)

    def test_hold_is_executable_and_has_runway(self):
        e=self.diag["mapping_events"]
        self.assertTrue(e.accepted_volume.gt(0).all())
        self.assertTrue(e.accepted_close.gt(0).all())
        self.assertTrue(e.accepted_days_to_expiry.ge(20).all())
        self.assertFalse(e.used_future_data.any())

    def test_expected_problem_dates_are_repaired(self):
        e=self.diag["mapping_events"].set_index("date")
        self.assertEqual(e.loc[pd.Timestamp("2020-06-15"),"accepted_contract"],"SC2009.INE")
        self.assertEqual(e.loc[pd.Timestamp("2020-09-09"),"accepted_contract"],"SC2012.INE")

    def test_panama_prefix(self):
        self.assertTrue(prefix_invariance_check(self.settings).passed.all())

    def test_legacy_mapping_is_not_modified(self):
        original=pd.read_pickle(ROOT/"data/normalized_v2/mapping.pkl")
        self.assertEqual(len(original),45773)
        self.assertEqual(original.loc[(pd.to_datetime(original.date)==pd.Timestamp("2020-06-15"))&(original.instrument=="SC"),"contract"].iloc[0],"SC2008.INE")


if __name__=="__main__": unittest.main()

