from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np
import pandas as pd
from five_sector_momentum.calendar_v4_2 import TradingCalendarV42
from five_sector_momentum.signals_v4_2 import weekly_select_v42, signal_bundle_v42
from five_sector_momentum.signals_v4 import build_forecast_library_v4, price_diff_sharpe
from five_sector_momentum.engine_v4_2 import BacktestEngineV42, SleeveEngineV42
from five_sector_momentum.engine_v4_1 import ScenarioV41, COST_SPECS
from five_sector_momentum.settings import Settings
from five_sector_momentum.costs_v3 import FeeSchedule
from test_core import synthetic_bundle
from test_v3 import fee_rules

ROOT=Path(__file__).resolve().parents[1]


def calendar(start='2014-01-01', end='2017-01-06', closed=()):
    d=pd.date_range(start,end)
    return TradingCalendarV42(pd.DataFrame({'exchange':'TEST','date':d,'is_open':[(int(x.weekday()<5 and x not in pd.to_datetime(list(closed)))) for x in d]}))


def setup(data=None):
    s=Settings.load(ROOT/'configs/five_sector_momentum_v4_2_repaired.yaml')
    data=synthetic_bundle() if data is None else data
    lib=build_forecast_library_v4(s,data); cal=calendar()
    signals={label:signal_bundle_v42(s,data,lib,forecast,label,cal) for label,forecast in [('single_20_skip5',lib.raw_skip5[20]),('single_250',lib.raw_regular[250])]}
    return s,data,cal,signals,FeeSchedule(fee_rules(data.instrument_meta.instrument.tolist()))


class CalendarTests(unittest.TestCase):
    def test_hand_wednesday_append_is_stable(self):
        c=calendar('2024-02-01','2024-02-09')
        d=pd.to_datetime(['2024-02-02','2024-02-05','2024-02-06','2024-02-07','2024-02-08','2024-02-09'])
        scores=pd.DataFrame({'RB':[1,1,1,-1,-1,-1]},index=d)
        elig=scores.notna(); meta=pd.DataFrame({'instrument':['RB'],'sector':['ferrous'],'mode':['absolute']})
        conf={'min_eligible_instruments':2,'long_threshold':0,'short_threshold':0}
        _,a,_=weekly_select_v42(scores.iloc[:4],elig.iloc[:4],meta,conf,c)
        _,b,_=weekly_select_v42(scores,elig,meta,conf,c)
        pd.testing.assert_frame_equal(a,b.iloc[:4].reset_index(drop=True))
        self.assertEqual(int(a.iloc[-1].direction),1)

    def test_holiday_short_week_and_cross_year(self):
        c=calendar('2025-12-29','2026-01-09',['2026-01-01','2026-01-02'])
        dates=pd.to_datetime(['2025-12-29','2025-12-30','2025-12-31','2026-01-05'])
        self.assertEqual(list(c.weekly_signal_dates(dates)),[pd.Timestamp('2025-12-31')])

    def test_missing_friday_bar_does_not_promote_thursday(self):
        c=calendar('2024-02-05','2024-02-09')
        self.assertEqual(len(c.weekly_signal_dates(pd.bdate_range('2024-02-05','2024-02-08'))),0)

    def test_missing_calendar_end_rejected(self):
        c=calendar('2024-02-05','2024-02-07')
        with self.assertRaises(ValueError): c.weekly_signal_dates(pd.bdate_range('2024-02-05','2024-02-07'))

    def test_conflicting_calendars_rejected(self):
        with self.assertRaises(ValueError):
            TradingCalendarV42(pd.DataFrame({'exchange':['A','B'],'date':['2024-02-05']*2,'is_open':[0,1]}))

    def test_entire_closed_week(self):
        d=pd.date_range('2024-02-05','2024-02-09')
        c=calendar('2024-02-05','2024-02-09',d)
        self.assertTrue(c.weekly_signal_dates(pd.DatetimeIndex([])).empty)

    def test_point_difference_windows_hand(self):
        x=pd.DataFrame({'X':np.arange(1.,301.)})
        for h,skip in [(20,5),(250,0)]:
            score=price_diff_sharpe(x,h,252,skip)
            self.assertTrue(score.iloc[:h+skip-1].isna().all().all())
            hand=x.iloc[-h-skip:len(x)-skip if skip else None,0]
            self.assertAlmostEqual(score.iloc[-1,0],hand.mean()/hand.std(ddof=1)*np.sqrt(252))


class RepairedIntegrationTests(unittest.TestCase):
    def test_both_forecasts_future_append_and_perturbation(self):
        s,d,c,signals,fees=setup(); cutoff=pd.Timestamp('2015-10-07')
        short=deepcopy(d)
        for name in ['bars','mapping','multiple_prices','adjusted_prices']:
            frame=getattr(short,name); setattr(short,name,frame.loc[frame.date.le(cutoff)].copy())
        _,_,_,prefix,_=setup(short)
        changed=deepcopy(d); changed.adjusted_prices.loc[changed.adjusted_prices.date.gt(cutoff),'adjusted_price']+=1e6
        _,_,_,future,_=setup(changed)
        for label in signals:
            for attr in ['scores','directions','daily_price_vol']:
                full=getattr(signals[label],attr); past=full.loc[full.date.le(cutoff)].reset_index(drop=True)
                pd.testing.assert_frame_equal(past,getattr(prefix[label],attr).reset_index(drop=True))
                frame=getattr(future[label],attr);pd.testing.assert_frame_equal(past,frame.loc[frame.date.le(cutoff)].reset_index(drop=True))

    def test_sleeve_and_single_account_prefix_invariance(self):
        s,d,c,signals,fees=setup(); cutoff=pd.Timestamp('2015-10-07')
        short=deepcopy(d)
        for name in ['bars','mapping','multiple_prices','adjusted_prices']:
            frame=getattr(short,name);setattr(short,name,frame.loc[frame.date.le(cutoff)].copy())
        ss,_,_,ps,_=setup(short)
        for sleeve in [False,True]:
            a=SleeveEngineV42(ss,short,ps,fees,c) if sleeve else BacktestEngineV42(ss,short,ps['single_20_skip5'],fees,c)
            b=SleeveEngineV42(s,d,signals,fees,c) if sleeve else BacktestEngineV42(s,d,signals['single_20_skip5'],fees,c)
            sc=ScenarioV41('test','test',COST_SPECS['C3'])
            ra,rb=a.run_v4_2(sc),b.run_v4_2(sc)
            for attr in ['equity','positions','targets','orders','fills','pnl_by_instrument']:
                x,y=getattr(ra,attr),getattr(rb,attr); dc='created_date' if attr=='orders' else 'date'
                pd.testing.assert_frame_equal(x.reset_index(drop=True),y.loc[y[dc].le(cutoff)].reset_index(drop=True),atol=1e-7,rtol=0)
            self.assertTrue((rb.fills.date>rb.fills.created_date).all())
            self.assertLess(abs(rb.equity.net_pnl.sum()-rb.pnl_by_instrument.net_pnl.sum()),.01)
            if sleeve:
                x,y=pd.DataFrame(a.internal_target_rows),pd.DataFrame(b.internal_target_rows)
                pd.testing.assert_frame_equal(x,y.loc[y.date.le(cutoff)].reset_index(drop=True),atol=1e-7,rtol=0)

    def test_fixed_budget_missing_share_opposition_and_one_constraint(self):
        s,d,c,signals,fees=setup();e=SleeveEngineV42(s,d,signals,fees,c)
        date=pd.Timestamp('2015-10-09');equity=10_000_000.;scenario=ScenarioV41('test','test').execution()
        for h in e.directions_by_horizon:
            for inst in e.instrument_meta.index:e.directions_by_horizon[h][(date,inst)]=0
        e.directions_by_horizon['single_20_skip5'][(date,'RB')]=1
        e.directions_by_horizon['single_250'][(date,'RB')]=-1
        targets,diag=e._calculate_targets(date,equity,{},scenario,[])
        self.assertEqual(targets,{})
        rows=pd.DataFrame(e.internal_target_rows)
        self.assertEqual(len(rows),10)
        self.assertTrue(np.allclose(rows.allocated_annual_risk,275000))
        self.assertTrue(all(x['internal_order_fees']==0 for x in e.net_target_rows))
        self.assertGreater(sum(x['cancelled_internal_lots'] for x in e.net_target_rows),0)
        with patch.object(e,'_scale_for_portfolio_constraints',wraps=e._scale_for_portfolio_constraints) as hard, patch.object(e,'_apply_buffer_fraction',wraps=e._apply_buffer_fraction) as buff:
            e._scheduled_targets(date,targets,{},equity,diag,scenario)
            self.assertEqual(hard.call_count,1);self.assertEqual(buff.call_count,1)


if __name__=='__main__': unittest.main(verbosity=2)
