from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import json
import os
import subprocess
import sys
import unittest

import numpy as np
import pandas as pd

from five_sector_momentum.analytics_v4_1 import (
    bootstrap_metrics, forecast_pair_correlations, moving_block_bootstrap,
    same_path_cost_study, slippage_components, validate_bootstrap_inputs,
)
from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.engine_v3 import PendingOrderV3
from five_sector_momentum.engine_v4_1 import (
    BacktestEngineV41, COST_SPECS, ScenarioV41, SleeveEngineV41,
    combined_sleeve_signal,
)
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4, signal_bundle_from_forecast, strict_equal_weight
from five_sector_momentum.workflow_v4_1 import _cost_elasticity
from test_core import synthetic_bundle
from test_v3 import fee_rules


ROOT=Path(__file__).resolve().parents[1]


def settings_v41():
    return Settings.load(ROOT/"configs"/"five_sector_momentum_v4_1.yaml")


def engine_and_signals(horizon=20):
    settings=settings_v41(); data=synthetic_bundle(); library=build_forecast_library_v4(settings,data)
    signals=signal_bundle_from_forecast(settings,data,library,library.raw_regular[horizon],f"single_{horizon}")
    fees=FeeSchedule(fee_rules(data.instrument_meta.instrument.tolist()))
    return settings,data,signals,fees


class CostAccountingV41Tests(unittest.TestCase):
    def test_component_addback_identity_and_hand_equity(self):
        dates=pd.bdate_range("2020-01-01",periods=2)
        equity=pd.DataFrame({"date":dates,"equity":[999990.0,1000010.0],"net_pnl":[-10.0,20.0],"fees":[2.0,3.0]})
        fills=pd.DataFrame({"date":dates,"commission":[2.0,3.0],"slippage_cost":[8.0,7.0],"base_slippage_ticks":[1.0,1.0],"roll_extra_ticks":[0.0,0.0],"impact_ticks":[0.0,0.0],"total_slippage_ticks":[1.0,1.0],"quantity":[1,1],"traded_notional":[1000.0,1000.0]})
        result=SimpleNamespace(equity=equity,fills=fills)
        daily,summary,_=same_path_cost_study("hand",result,1_000_000.0,"2021-01-01")
        self.assertEqual(daily.same_path_pre_cost_pnl.tolist(),[0.0,30.0])
        self.assertEqual(daily.same_path_pre_cost_equity.tolist(),[1_000_000.0,1_000_030.0])
        self.assertAlmostEqual(summary.loc[summary.period.eq("full"),"total_cost_drag"].iloc[0],20.0)
        parts=slippage_components(fills)
        np.testing.assert_allclose(parts[["base_slippage_cost","roll_slippage_cost","impact_cost"]].sum(axis=1),fills.slippage_cost)

    def test_registered_cost_components_are_exact(self):
        self.assertEqual(COST_SPECS["C0"].fee_multiplier,0.0)
        self.assertFalse(COST_SPECS["C0"].impact_enabled)
        self.assertEqual(COST_SPECS["C0"].roll_ticks,0)
        self.assertEqual(COST_SPECS["C1"].base_mode,"zero")
        self.assertEqual(COST_SPECS["C2"].base_shift_ticks,-1)
        self.assertEqual(COST_SPECS["C3"].base_shift_ticks,0)
        self.assertEqual(COST_SPECS["C4"].base_shift_ticks,1)
        self.assertEqual(COST_SPECS["C5"].base_shift_ticks,2)
        self.assertEqual(COST_SPECS["C6"].fixed_ticks,2)
        self.assertEqual(COST_SPECS["C7"].fixed_ticks,3)

    def test_c0_keeps_limit_rejection_and_partial_fill(self):
        settings,data,signals,fees=engine_and_signals(); engine=BacktestEngineV41(settings,data,signals,fees)
        engine._cost=COST_SPECS["C0"]; engine.execution=dict(settings.section("execution")); engine.execution["roll_extra_ticks"]=0
        date=data.mapping.date.iloc[-1]; contract="RB99.TEST"
        engine.bars.loc[(date,contract),"open"]=5000.0
        engine.liquidity[(date,"RB")]={"median_volume":10_000.0,"median_open_interest":50_000.0}
        order=PendingOrderV3(contract,"RB",800,date,"normal_rebalance",1)
        fills,remainder,rejection=engine._execute_order_v3(date,order,ScenarioV41("c0","test",COST_SPECS["C0"]).execution(),{})
        self.assertEqual(sum(abs(x["quantity"]) for x in fills),500); self.assertEqual(remainder,300); self.assertEqual(rejection["reason"],"partial_fill")
        self.assertEqual(sum(x["commission"]+x["slippage_cost"] for x in fills),0.0)
        engine.bars.loc[(date,contract),"upper_limit"]=engine.bars.loc[(date,contract),"open"]
        locked=PendingOrderV3(contract,"RB",1,date,"normal_rebalance",1)
        fills,_,rejection=engine._execute_order_v3(date,locked,ScenarioV41("c0","test",COST_SPECS["C0"]).execution(),{})
        self.assertEqual(fills,[]); self.assertEqual(rejection["reason"],"adverse_limit_at_open")

    def test_cost_changes_causally_change_later_sizing(self):
        settings,data,signals,fees=engine_and_signals()
        c0=BacktestEngineV41(settings,data,signals,fees).run_v4_1(ScenarioV41("c0","test",COST_SPECS["C0"]))
        c7=BacktestEngineV41(settings,data,signals,fees).run_v4_1(ScenarioV41("c7","test",COST_SPECS["C7"]))
        self.assertNotEqual(float(c0.equity.equity.iloc[-1]),float(c7.equity.equity.iloc[-1]))
        joined=c0.targets.merge(c7.targets,on=["date","contract"],suffixes=("_c0","_c7"))
        self.assertTrue((joined.optimal_position_c0!=joined.optimal_position_c7).any())

    def test_break_even_only_interpolates_adjacent_points(self):
        rows=[]
        for code,pnl,sr in [("C0",100,100),("C1",90,90),("C2",20,20),("C3",10,10),("C4",-10,-10),("C5",-20,-20),("C6",-30,-30),("C7",-40,-40)]:
            rows.append({"strategy":"X","period":"full","cost_code":code,"净利润_元":pnl,"夏普比率":sr/100,"年化收益率":sr/1000,"最大回撤":-.1,"commission":1,"base_slippage":2,"roll_slippage":3,"impact":4})
        out=_cost_elasticity(pd.DataFrame(rows),settings_v41())
        be=out[out.comparison.eq("break_even_normal_tick_shift")].iloc[0]
        self.assertEqual(be.break_even_status,"区间内穿越"); self.assertAlmostEqual(be.break_even_shift_ticks,.5)


class ForecastAndSleeveV41Tests(unittest.TestCase):
    def test_strict_equal_weight_and_manual_effective_weight(self):
        a=pd.DataFrame({"X":[2.0,2.0]}); b=pd.DataFrame({"X":[6.0,np.nan]})
        combined=strict_equal_weight([a,b]); self.assertEqual(combined.loc[0,"X"],4.0); self.assertTrue(pd.isna(combined.loc[1,"X"]))
        effective=abs(.5*2)/(abs(.5*2)+abs(.5*6)); self.assertEqual(effective,.25)
        self.assertNotEqual(np.sign((2-3)/2),np.sign(2/2))

    def test_forecast_correlations_are_per_instrument_and_raw_scaled(self):
        settings,data,_,_=engine_and_signals(); lib=build_forecast_library_v4(settings,data)
        out=forecast_pair_correlations(lib,data.instrument_meta,"2022-01-01",.25)
        self.assertEqual(set(out.basis),{"raw","scaled"}); self.assertGreater(out.instrument.nunique(),1)
        self.assertTrue((out.scope.eq("full")).any())

    def test_sleeve_budget_unused_share_and_opposite_netting(self):
        settings,data,_,fees=engine_and_signals(); lib=build_forecast_library_v4(settings,data)
        by={h:signal_bundle_from_forecast(settings,data,lib,lib.raw_regular[h],f"single_{h}") for h in [20,60,120]}
        date=data.mapping.date.max()
        for h,bundle in by.items():
            bundle.directions.loc[bundle.directions.date.eq(date),"direction"]=0
        # Equal and opposite RB sleeves cancel on the same true contract; third sleeve is unused.
        by[20].directions.loc[(by[20].directions.date.eq(date))&(by[20].directions.instrument.eq("RB")),"direction"]=1
        by[60].directions.loc[(by[60].directions.date.eq(date))&(by[60].directions.instrument.eq("RB")),"direction"]=-1
        combined=combined_sleeve_signal(by); engine=SleeveEngineV41(settings,data,by,combined,fees)
        targets,_=engine._calculate_targets(date,10_000_000.0,{},ScenarioV41("s","test").execution(),[])
        self.assertNotIn("RB99.TEST",targets)
        internal=pd.DataFrame(engine.internal_target_rows)
        allocated=internal.groupby(["horizon","sector"]).allocated_annual_risk.sum()
        expected=10_000_000*.275*.20/3
        np.testing.assert_allclose(allocated.values,expected)
        unused=internal[(internal.horizon.eq(120))&(internal.sector.eq("ferrous"))]
        self.assertTrue(unused.unused_signal_share.all())

    def test_nonweekly_scheduler_uses_true_net_target_not_direction_votes(self):
        settings,data,_,fees=engine_and_signals(); lib=build_forecast_library_v4(settings,data)
        by={h:signal_bundle_from_forecast(settings,data,lib,lib.raw_regular[h],str(h)) for h in [20,60,120]}
        combined=combined_sleeve_signal(by); engine=SleeveEngineV41(settings,data,by,combined,fees)
        date=next(d for d in sorted(data.mapping.date.unique()) if d not in engine.weekly_signal_dates)
        contract=engine.mapping[(date,"RB")]
        engine.directions[(date,"RB")]=0  # the old vote-based failure state
        desired,_,reasons=engine._scheduled_targets(date,{contract:15},{contract:10},10_000_000.0,{"trailing_realized_volatility":.10},ScenarioV41("s","test").execution())
        self.assertEqual(desired[contract],10)
        self.assertNotIn(contract,reasons)

    def test_future_append_does_not_change_past_sleeve_directions(self):
        settings,data,_,_=engine_and_signals(); cutoff=data.adjusted_prices.date.sort_values().unique()[-30]
        changed=deepcopy(data); changed.adjusted_prices.loc[changed.adjusted_prices.date>cutoff,"adjusted_price"]+=1_000_000
        first=build_forecast_library_v4(settings,data); second=build_forecast_library_v4(settings,changed)
        a={h:signal_bundle_from_forecast(settings,data,first,first.raw_regular[h],str(h)) for h in [20,60,120]}
        b={h:signal_bundle_from_forecast(settings,changed,second,second.raw_regular[h],str(h)) for h in [20,60,120]}
        da=combined_sleeve_signal(a).directions; db=combined_sleeve_signal(b).directions
        pd.testing.assert_frame_equal(da[da.date<=cutoff].reset_index(drop=True),db[db.date<=cutoff].reset_index(drop=True))


class BootstrapV41Tests(unittest.TestCase):
    def _returns(self):
        index=pd.bdate_range("2021-11-01",periods=90); rng=np.random.default_rng(4)
        net=pd.DataFrame(rng.normal(.0001,.01,(90,21)),index=index,columns=[f"s{i:02d}" for i in range(21)])
        return net,net+.00001

    def test_seed_shared_blocks_boundaries_and_path_drawdown(self):
        net,pre=self._returns(); validate_bootstrap_inputs(net,pre,list(net.columns))
        a,blocks,_=moving_block_bootstrap(net,pre,"2022-01-03",20260902,20,5)
        b,blocks2,_=moving_block_bootstrap(net,pre,"2022-01-03",20260902,20,5)
        pd.testing.assert_frame_equal(a,b); pd.testing.assert_frame_equal(blocks,blocks2)
        self.assertEqual(a.strategy.nunique(),21)
        split=pd.Timestamp("2022-01-03")
        self.assertTrue((blocks.loc[blocks.phase.eq("insample"),"start_date"]<split).all())
        self.assertTrue((blocks.loc[blocks.phase.eq("validation"),"start_date"]>=split).all())
        x=np.array([.10,-.10,-.10,.05]); wealth=np.cumprod(1+x); expected=(wealth/np.maximum.accumulate(wealth)-1).min()
        self.assertAlmostEqual(bootstrap_metrics(x)["max_drawdown"],expected)

    def test_missing_account_day_fails_instead_of_zero_fill(self):
        net,pre=self._returns(); pre=pre.drop(pre.index[10])
        with self.assertRaises(AssertionError): validate_bootstrap_inputs(net,pre,list(net.columns))

    def test_cross_process_strategy_order_is_deterministic(self):
        code="import json; from five_sector_momentum.workflow_v4_1 import V4_DIRS; print(json.dumps(list(V4_DIRS)))"
        env=os.environ.copy(); env["PYTHONPATH"]=str(ROOT/"src")
        first=subprocess.check_output([sys.executable,"-c",code],cwd=ROOT,env=env,text=True).strip()
        second=subprocess.check_output([sys.executable,"-c",code],cwd=ROOT,env=env,text=True).strip()
        self.assertEqual(first,second); self.assertEqual(len(json.loads(first)),18)


if __name__=="__main__":
    unittest.main()
