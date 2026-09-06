"""Read-only v4.2 preflight. A legacy causality failure is NOT an expected failure."""
from pathlib import Path
from types import SimpleNamespace
import unittest

import pandas as pd

from five_sector_momentum.settings import Settings
from five_sector_momentum.signals import _weekly_select, build_liquidity_measures
from five_sector_momentum.signals_v4 import price_diff_sharpe


ROOT = Path(__file__).resolve().parents[1]


class V42PreflightTests(unittest.TestCase):
    evidence = {}

    @classmethod
    def setUpClass(cls):
        cls.settings = Settings.load(ROOT / 'configs/five_sector_momentum_v4_2.yaml')
        research = cls.settings.section('v4_2_research')
        cls.cutoff = pd.Timestamp(research['preflight_cutoff'])
        cls.end = pd.Timestamp(research['preflight_extended_end'])
        base = ROOT / 'data/normalized_v2'
        prices = pd.read_pickle(base / 'adjusted_prices.pkl')
        cls.prices = prices.pivot(index='date', columns='instrument', values='adjusted_price').sort_index().loc[:cls.end]
        cls.meta = pd.read_pickle(base / 'instrument_meta.pkl')
        data = SimpleNamespace(bars=pd.read_pickle(base / 'bars.pkl'), mapping=pd.read_pickle(base / 'mapping.pkl'))
        cls.eligible, _, _ = build_liquidity_measures(data, cls.settings.section('eligibility'), cls.prices.index)
        prefix_data = SimpleNamespace(bars=data.bars.loc[data.bars.date.le(cls.cutoff)], mapping=data.mapping.loc[data.mapping.date.le(cls.cutoff)])
        cls.prefix_eligible, _, _ = build_liquidity_measures(prefix_data, cls.settings.section('eligibility'), cls.prices.loc[:cls.cutoff].index)

    def test_01_forecasts_and_eligibility_are_prefix_invariant(self):
        rows = []
        for label, window, skip in [('single_20_skip5', 20, 5), ('single_250', 250, 0)]:
            short = price_diff_sharpe(self.prices.loc[:self.cutoff].diff(), window, 252, skip)
            extended = price_diff_sharpe(self.prices.diff(), window, 252, skip).loc[:self.cutoff]
            pd.testing.assert_frame_equal(short, extended, check_exact=True)
            rows.append({'signal': label, 'check': 'raw_forecast_prefix', 'passed': True, 'rows': len(short), 'cutoff': self.cutoff})
        # A later listing adds an all-False historical eligibility column.
        # Check shared instruments exactly AND require added columns to be False;
        # do not mistake the structural column expansion for future information.
        full_prefix = self.eligible.loc[:self.cutoff]
        shared = self.prefix_eligible.columns
        pd.testing.assert_frame_equal(self.prefix_eligible, full_prefix.reindex(columns=shared), check_exact=True)
        added = full_prefix.columns.difference(shared)
        self.assertFalse(full_prefix[added].any().any(), 'Future-listed instruments must remain historically ineligible')
        self.evidence['eligibility_column_alignment'] = pd.DataFrame([
            {'instrument': item, 'in_prefix_columns': item in shared, 'eligible_days_before_cutoff': int(full_prefix[item].sum())}
            for item in full_prefix.columns
        ])
        rows.append({'signal': 'both', 'check': 'liquidity_eligibility_prefix', 'passed': True, 'rows': len(self.prefix_eligible), 'cutoff': self.cutoff})
        self.evidence['forecast_prefix_checks'] = pd.DataFrame(rows)

    def test_02_weekly_directions_must_not_change_when_future_dates_are_appended(self):
        # Human-checkable: last Friday score=+1; Wednesday score=-1.
        # No past value is changed; only Thursday and Friday are appended.
        dates = pd.to_datetime(['2024-02-02', '2024-02-05', '2024-02-06', '2024-02-07', '2024-02-08', '2024-02-09'])
        hand = pd.DataFrame({'RB': [1., 1., 1., -1., -1., -1.]}, index=dates)
        hand_meta = pd.DataFrame({'instrument': ['RB'], 'sector': ['ferrous'], 'mode': ['absolute']})
        hand_ok = pd.DataFrame(True, index=dates, columns=['RB'])
        cases = [('hand_weekly_schedule', hand, hand_ok, hand_meta, pd.Timestamp('2024-02-07'))]
        for label, window, skip in [('single_20_skip5', 20, 5), ('single_250', 250, 0)]:
            forecast = price_diff_sharpe(self.prices.diff(), window, 252, skip)
            cases.append((label, forecast, self.eligible, self.meta, self.cutoff))
        comparisons = []
        selected = []
        for label, scores, eligible, meta, cutoff in cases:
            short_selections, short, _ = _weekly_select(scores.loc[:cutoff], eligible.loc[:cutoff], meta, self.settings.section('signal'))
            long_selections, extended, _ = _weekly_select(scores, eligible, meta, self.settings.section('signal'))
            comparison = short.merge(extended.loc[extended.date.le(cutoff)], on=['date', 'instrument', 'sector'], suffixes=('_prefix', '_extended'), validate='one_to_one')
            comparison['signal_date_equal'] = comparison.signal_date_prefix.eq(comparison.signal_date_extended) | (comparison.signal_date_prefix.isna() & comparison.signal_date_extended.isna())
            comparison['direction_equal'] = comparison.direction_prefix.eq(comparison.direction_extended)
            comparison.insert(0, 'case', label)
            comparisons.append(comparison)
            for scope, frame in [('prefix', short_selections), ('extended', long_selections.loc[long_selections.signal_date.le(cutoff)])]:
                frame = frame.copy()
                frame.insert(0, 'scope', scope)
                frame.insert(0, 'case', label)
                selected.append(frame)
        all_rows = pd.concat(comparisons, ignore_index=True)
        mismatch = all_rows.loc[~all_rows.signal_date_equal | ~all_rows.direction_equal].copy()
        self.evidence['weekly_prefix_comparison'] = all_rows
        self.evidence['weekly_prefix_mismatches'] = mismatch
        self.evidence['weekly_prefix_selections'] = pd.concat(selected, ignore_index=True)
        self.evidence['hand_input'] = hand.rename_axis('date').reset_index()
        self.assertTrue(mismatch.empty, f'Future-date append changes {len(mismatch)} historical direction/signal-date rows; direction changes={int((~mismatch.direction_equal).sum())}. Stop v4.2 before G1/G2/S1/S2.')


if __name__ == '__main__':
    unittest.main(failfast=True, verbosity=2)
