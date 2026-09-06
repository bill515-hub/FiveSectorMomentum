import hashlib
import os
from pathlib import Path
import subprocess
import sys
import unittest
import numpy as np
import pandas as pd
from five_sector_momentum.analytics_v4_2 import drawdowns, metrics, event_table, corr, bootstrap_indices, conditions


class AnalyticsTests(unittest.TestCase):
    def test_initial_loss_drawdown_anchor_and_recovery(self):
        r=pd.Series([-.5,1.,-.1],index=pd.bdate_range('2020-01-01',periods=3))
        np.testing.assert_allclose(drawdowns(r),[-.5,0.,-.1])
        events=event_table(r)
        self.assertEqual(len(events),2)
        self.assertTrue(events.iloc[0].recovered)
        self.assertFalse(events.iloc[1].recovered)
        self.assertEqual(events.iloc[0].underwater_days,1)
        self.assertEqual(metrics(r)['mdd'],-.5)

    def test_sortino_uses_all_observations(self):
        r=np.array([-.1,.2])
        expected=r.mean()*252/(np.sqrt((.1**2)/2)*np.sqrt(252))
        self.assertAlmostEqual(metrics(r)['sortino'],expected)

    def test_condition_observation_limit_and_missing_returns(self):
        self.assertTrue(np.isnan(corr(np.arange(19),np.arange(19))))
        self.assertAlmostEqual(corr(np.arange(20),np.arange(20)),1.)
        with self.assertRaises(ValueError):drawdowns([0.,np.nan])

    def test_joint_blocks_and_end_truncation(self):
        starts,idx=bootstrap_indices(43,5)
        self.assertEqual(idx.shape,(5,43))
        self.assertTrue((idx>=0).all() and (idx<43).all())
        x=np.arange(43);y=2*x
        np.testing.assert_array_equal(y[idx],2*x[idx])
        for row in idx:
            np.testing.assert_array_equal(np.diff(row[:20]),np.ones(19))
        _,other=bootstrap_indices(43,5);np.testing.assert_array_equal(idx,other)

    def test_block_indices_cross_process_deterministic(self):
        root=Path(__file__).resolve().parents[1];env=os.environ.copy();env['PYTHONPATH']=str(root/'src');env['PYTHONDONTWRITEBYTECODE']='1'
        code='from five_sector_momentum.analytics_v4_2 import bootstrap_indices; import hashlib; print(hashlib.sha256(bootstrap_indices(43,5)[1].tobytes()).hexdigest())'
        a=subprocess.check_output([sys.executable,'-B','-c',code],env=env)
        b=subprocess.check_output([sys.executable,'-B','-c',code],env=env)
        self.assertEqual(a,b)

    def test_drawdown_states_recomputed_on_resampled_path(self):
        a=np.array([.1,-.09,-.02,.2]);idx=np.array([1,0,3,2])
        self.assertFalse(np.allclose(drawdowns(a)[idx],drawdowns(a[idx])))
        c=conditions(a,a,drawdowns(a),drawdowns(a))
        self.assertFalse(c['any_only_one'].any())

    def test_rolling_correlation_future_append(self):
        rng=np.random.default_rng(9);x=pd.Series(rng.normal(size=300));y=pd.Series(rng.normal(size=300))
        for window in [63,126,252]:
            a=x.iloc[:280].rolling(window,min_periods=window).corr(y.iloc[:280])
            b=x.rolling(window,min_periods=window).corr(y).iloc[:280]
            pd.testing.assert_series_equal(a,b)


if __name__=='__main__':unittest.main(verbosity=2)
