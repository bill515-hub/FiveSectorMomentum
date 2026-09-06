from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from five_sector_momentum.analytics_v4_1 import (
    bootstrap_summaries, moving_block_bootstrap, returns_from_result,
    validate_bootstrap_inputs,
)
from five_sector_momentum.costs_v3 import FeeSchedule
from five_sector_momentum.data_pipeline import load_bundle
from five_sector_momentum.engine_v4_1 import COST_SPECS, ScenarioV41, SleeveEngineV41, combined_sleeve_signal
from five_sector_momentum.settings import Settings
from five_sector_momentum.signals_v4 import build_forecast_library_v4, signal_bundle_from_forecast
from five_sector_momentum.workflow_v4_1 import (
    V4_DIRS, _accounting, _both, _execution_stats, _load_result,
    _point_winner_stability, _save_result, _sleeve_detail_tables,
    _sleeve_netting, _sleeve_risk_summary, _version_comparison,
)


def main() -> None:
    parser=argparse.ArgumentParser(description="修复v4.1袖套非周度退出并使用剩余6次注册上限")
    parser.add_argument("root")
    args=parser.parse_args()
    project=Path(__file__).resolve().parents[1]; root=(project/args.root).resolve()
    if root.parent!=(project/"outputs").resolve() or not root.name.startswith("v4_1_"): raise ValueError("invalid v4.1 root")
    if list(root.glob("04_corrected_sleeve__*")): raise RuntimeError("corrected sleeves already exist; refusing duplicate engine runs")
    settings=Settings.load(project/"configs/five_sector_momentum_v4_1.yaml")
    data=load_bundle(settings); library=build_forecast_library_v4(settings,data)
    fees=FeeSchedule.load(project/settings.section("fees")["rules_path"])
    signals={h:signal_bundle_from_forecast(settings,data,library,library.raw_regular[h],f"single_{h}") for h in [20,60,120,180,250]}

    old_internal=pd.read_pickle(root/"sleeve_internal_targets_v4_1.pkl")
    _both(old_internal,root/"invalidated_initial_sleeve_internal_targets_v4_1")
    old_results={d.name.split("__",1)[1]:_load_result(d) for d in root.glob("03_sleeve__*")}
    corrected={}; internal=[]
    for name,horizons in settings.section("v4_1_research")["sleeves"].items():
        by={int(h):signals[int(h)] for h in horizons}; combined=combined_sleeve_signal(by)
        for code,suffix in [("C3",""),("C7","_fixed_3tick")]:
            label=f"strategy_sleeve_{name}_equal_risk{suffix}"; scenario=ScenarioV41(label,"04_corrected_sleeve",COST_SPECS[code])
            engine=SleeveEngineV41(settings,data,by,combined,fees); result=engine.run_v4_1(scenario)
            _save_result(root/scenario.name,result,combined,pd.DataFrame(engine.internal_target_rows)); corrected[label]=result
            frame=pd.DataFrame(engine.internal_target_rows); frame["strategy"]=label; internal.append(frame)
    internal=pd.concat(internal,ignore_index=True); _both(internal,root/"sleeve_internal_targets_v4_1")
    _both(_sleeve_risk_summary(internal),root/"sleeve_risk_contribution_v4_1")
    _both(_sleeve_netting(internal,corrected,data.bars),root/"sleeve_netting_v4_1")
    metrics=[]
    from five_sector_momentum.workflow_v4_1 import _result_period_metrics
    for label,result in corrected.items(): metrics.extend(_result_period_metrics(label,"C7" if "fixed" in label else "C3",result,settings))
    _both(pd.DataFrame(metrics),root/"sleeve_metrics_v4_1")
    for name,frame in _sleeve_detail_tables(corrected,settings).items(): _both(frame,root/name)

    source=project/settings.section("v4_1_research")["source_v4_output"]
    source_results={label:_load_result(source/path) for label,path in V4_DIRS.items()}
    _both(_version_comparison(project,source_results,corrected,settings),root/"v3_v4_v4_1_comparison")
    base21={"reference_v3_252":source_results["reference_v3_252"],**{k:v for k,v in source_results.items() if k!="reference_v3_252"},**{k:v for k,v in corrected.items() if "fixed" not in k}}
    net=pd.concat({k:returns_from_result(v,False) for k,v in base21.items()},axis=1); pre=pd.concat({k:returns_from_result(v,True) for k,v in base21.items()},axis=1); validate_bootstrap_inputs(net,pre,list(base21))
    b=settings.section("v4_1_research")["bootstrap"]; draws,blocks,ranks=moving_block_bootstrap(net,pre,settings.section("run")["sample_split"],int(b["seed"]),int(b["block_length"]),int(b["repetitions"])); summary,paired,paired_summary,stability,mean_winner=bootstrap_summaries(draws,ranks)
    for name,frame in [("bootstrap_strategy_draws_v4_1",draws),("bootstrap_block_draws_v4_1",blocks),("bootstrap_ranks_full_v4_1",ranks),("bootstrap_strategy_summary_v4_1",summary),("bootstrap_paired_differences_v4_1",paired),("bootstrap_paired_summary_v4_1",paired_summary),("bootstrap_rank_stability_v4_1",stability),("bootstrap_mean_winner_v4_1",mean_winner),("bootstrap_point_winner_stability_v4_1",_point_winner_stability(net,pre,ranks))]: _both(frame,root/name)

    matrix=pd.read_pickle(root/"cost_response_matrix_v4_1.pkl"); matrix_results={}
    for _,row in matrix.drop_duplicates(["strategy","cost_code"]).iterrows(): matrix_results[f"{row.strategy}_{row.cost_code}"]=_load_result(Path(row.source_path))
    account=_accounting({**source_results,**corrected,**matrix_results},float(settings.section("run")["initial_capital"])); _both(account,root/"accounting_reconciliation_v4_1")
    if not account.passed.all(): raise AssertionError("corrected accounting failed")
    rebalance,margin=_execution_stats({**source_results,**corrected,**matrix_results}); _both(rebalance,root/"rebalance_buffer_statistics_v4_1"); _both(margin,root/"margin_leverage_v4_1")
    audit=[]
    for label,new in corrected.items():
        old=old_results[label]
        audit.append({"strategy":label,"status":"初版无效，修正版有效","old_orders":len(old.orders),"new_orders":len(new.orders),"order_change":len(new.orders)-len(old.orders),"old_fill_lots":old.fills.quantity.abs().sum(),"new_fill_lots":new.fills.quantity.abs().sum(),"old_total_cost":old.fills.commission.sum()+old.fills.slippage_cost.sum(),"new_total_cost":new.fills.commission.sum()+new.fills.slippage_cost.sum(),"old_ending_equity":old.equity.equity.iloc[-1],"new_ending_equity":new.equity.equity.iloc[-1],"cause":"方向票数为0不等于真实合约净目标为0；非周度退出改用最终净optimal"})
    _both(pd.DataFrame(audit),root/"sleeve_correction_audit_v4_1")
    _both(pd.DataFrame([{"stage":"reproduction_gate","engine_runs":4,"status":"valid"},{"stage":"cost_counterfactual","engine_runs":43,"status":"valid"},{"stage":"initial_sleeves","engine_runs":6,"status":"invalidated_but_retained"},{"stage":"corrected_sleeves","engine_runs":6,"status":"valid"},{"stage":"total_actual","engine_runs":59,"status":"at_task_cap"},{"stage":"valid_registered_results","engine_runs":53,"status":"4+43+6"}]),root/"engine_run_count_v4_1")
    manifest=json.loads((root/"manifest.json").read_text(encoding="utf-8")); manifest.update({"new_engine_runs":59,"valid_registered_engine_results":53,"invalidated_engine_runs_retained":6,"sleeve_correction":"complete"}); (root/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(f"corrected six sleeves; actual engine run count is 59: {root}")


if __name__=="__main__": main()
