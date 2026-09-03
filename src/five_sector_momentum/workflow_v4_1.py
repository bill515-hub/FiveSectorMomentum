from __future__ import annotations

import json, os, shutil, subprocess, sys
from pathlib import Path
import numpy as np
import pandas as pd

from .analytics_v4 import concentration_v4, metrics_from_equity, pnl_contribution_v4, robustness_v4, rolling_walk_forward_v4, yearly_performance_v4
from .analytics_v4_1 import *
from .costs_v3 import FeeSchedule
from .data_pipeline import load_bundle
from .engine import BacktestResult
from .engine_v4_1 import BacktestEngineV41, SleeveEngineV41, ScenarioV41, COST_SPECS, combined_sleeve_signal
from .settings import Settings
from .signals import SignalBundle
from .signals_v4 import build_forecast_library_v4, signal_bundle_from_forecast, aggregate_from_library
from .storage import read_frame, write_json
from .workflow_v4 import registered_v4_scenarios, forecast_for_scenario


V4_DIRS={
"reference_v3_252":"00_reference__reference_v3_252","single_20":"01_single_normal__single_20","single_60":"01_single_normal__single_60","single_120":"01_single_normal__single_120","single_180":"01_single_normal__single_180","single_250":"01_single_normal__single_250","single_20_skip5":"02_single_skip__single_20_skip5","single_60_skip5":"02_single_skip__single_60_skip5","single_120_skip5":"02_single_skip__single_120_skip5","single_180_skip5":"02_single_skip__single_180_skip5","single_250_skip5":"02_single_skip__single_250_skip5","single_250_minus_20":"02_single_skip__single_250_minus_20","multi_fast_raw":"03_multi__multi_fast_raw","multi_fast_scaled":"03_multi__multi_fast_scaled","multi_all_raw":"03_multi__multi_all_raw","multi_all_scaled":"03_multi__multi_all_scaled","multi_slow_raw":"03_multi__multi_slow_raw","multi_slow_scaled":"03_multi__multi_slow_scaled"}


def run_v4_1(settings: Settings, resume_root: Path | None = None)->Path:
    if settings.raw.get("version")!="v4_1": raise ValueError("v4_1 config required")
    project=settings.path.parent.parent; source=project/settings.section("v4_1_research")["source_v4_output"]
    root=Path(resume_root).resolve() if resume_root is not None else project/"outputs"/f"v4_1_{pd.Timestamp.now():%Y%m%d_%H%M%S}"
    if resume_root is None:
        root.mkdir(parents=True,exist_ok=False)
        shutil.copy2(settings.path,root/settings.path.name); shutil.copy2(project/"V4_1_EXPERIMENT_REGISTRY.md",root/"V4_1_EXPERIMENT_REGISTRY.md")
        _tests(project,root)
    elif not root.is_dir() or root.parent.resolve() != (project/"outputs").resolve() or not root.name.startswith("v4_1_"):
        raise ValueError("resume_root must be an existing v4.1 output directory")
    else:
        _tests(project,root)
    data=load_bundle(settings); lib=build_forecast_library_v4(settings,data); fees=FeeSchedule.load(project/settings.section("fees")["rules_path"])
    base_specs={s.label:s for s in registered_v4_scenarios(settings) if s.stage in {"00_reference","01_single_normal","02_single_skip","03_multi"}}
    signals={label:signal_bundle_from_forecast(settings,data,lib,forecast_for_scenario(lib,spec),label) for label,spec in base_specs.items()}
    source_results={label:_load_result(source/V4_DIRS[label]) for label in V4_DIRS}
    run_count=0; gate_results={}; gate_rows=[]
    gate_labels=["reference_v3_252","single_180_skip5","multi_all_raw","multi_fast_scaled"]
    for label in gate_labels:
        sc=ScenarioV41(f"gate_{label}","00_gate",COST_SPECS["C3"]); saved=root/sc.name
        if resume_root is not None and saved.is_dir():
            result=_load_result(saved)
        else:
            result=BacktestEngineV41(settings,data,signals[label],fees).run_v4_1(sc); _save_result(saved,result,signals[label])
        run_count+=1; gate_results[label]=result
        gate_rows.extend(_compare_gate(label,signals[label],result,source/V4_DIRS[label],source_results[label]))
    gate=pd.DataFrame(gate_rows); _both(gate,root/"reproduction_gate_v4_1")
    if not gate.passed.all():
        write_json({"status":"gate_failed","new_engine_runs":run_count},root/"manifest.json"); raise RuntimeError("v4.1 reproduction gate failed")

    # 17 frozen-path cost add-backs and event attribution.
    daily=[]; summaries=[]; annual=[]; events=[]
    candidates=[x for x in V4_DIRS if x!="reference_v3_252"]
    for label in candidates:
        d,s,a=same_path_cost_study(label,source_results[label],float(settings.section("run")["initial_capital"]),settings.section("run")["sample_split"])
        daily.append(d); summaries.append(s); annual.append(a); events.append(cost_event_attribution(label,source_results[label],data.instrument_meta))
    _both(pd.concat(daily,ignore_index=True),root/"same_path_daily_v4_1"); _both(pd.concat(summaries,ignore_index=True),root/"same_path_cost_summary_v4_1"); _both(pd.concat(annual,ignore_index=True),root/"same_path_yearly_v4_1"); _both(pd.concat(events,ignore_index=True),root/"cost_turnover_attribution_v4_1")

    # Fixed 56-cell cost matrix; reuse only exact pre-registered sources.
    representatives=settings.section("v4_1_research")["representative_signals"]; matrix=[]; matrix_results={}
    reuse={
      ("reference_v3_252","C6"):project/"outputs/v3_20260902_001129/06_break_even_tick__break_even_tick_2",
      ("reference_v3_252","C7"):project/"outputs/v3_20260902_001129/06_break_even_tick__break_even_tick_3",
      ("single_180_skip5","C6"):source/"05_pressure__single_180_skip5_fixed_2tick",
      ("single_180_skip5","C7"):source/"05_pressure__single_180_skip5_fixed_3tick",
      ("multi_all_raw","C6"):source/"05_pressure__multi_all_raw_fixed_2tick",
      ("multi_all_raw","C7"):source/"05_pressure__multi_all_raw_fixed_3tick"}
    for label in representatives:
      for code in settings.section("v4_1_research")["cost_scenarios"]:
        source_kind="new"; source_path=""
        if code=="C3": result=gate_results.get(label,source_results[label]); source_kind="gate" if label in gate_results else "v4_reference"; source_path=str(source/V4_DIRS[label])
        elif (label,code) in reuse: result=_load_result(reuse[(label,code)]); source_kind="existing_exact"; source_path=str(reuse[(label,code)])
        else:
          sc=ScenarioV41(f"{label}_{code}","02_cost",COST_SPECS[code]); saved=root/sc.name
          if resume_root is not None and saved.is_dir(): result=_load_result(saved)
          else: result=BacktestEngineV41(settings,data,signals[label],fees).run_v4_1(sc); _save_result(saved,result,signals[label])
          run_count+=1; source_path=str(saved)
        _assert_cost_result(code,result)
        matrix_results[(label,code)]=result; rows=_result_period_metrics(label,code,result,settings)
        for row in rows: row.update({"source_kind":source_kind,"source_path":source_path}); matrix.append(row)
    matrix=pd.DataFrame(matrix); _both(matrix,root/"cost_response_matrix_v4_1")
    elasticity=_cost_elasticity(matrix,settings); _both(elasticity,root/"cost_elasticity_break_even_v4_1")

    # Forecast influence and three-layer correlation.
    influence,selection_change=weekly_forecast_influence(lib,settings,data.instrument_meta); _both(influence,root/"forecast_horizon_influence_v4_1"); _both(selection_change,root/"selection_omission_changes_v4_1")
    _both(_forecast_influence_summary(influence,selection_change),root/"forecast_horizon_influence_summary_v4_1")
    fcorr=forecast_pair_correlations(lib,data.instrument_meta,settings.section("run")["sample_split"],float(settings.section("v4_1_research")["zero_near_forecast"])); _both(fcorr,root/"forecast_pair_correlations_v4_1")
    _both(_forecast_correlation_summary(fcorr),root/"forecast_pair_correlation_summary_v4_1")
    sover=selection_pair_overlap(lib,data.instrument_meta,settings.section("run")["sample_split"]); _both(sover,root/"selection_pair_overlap_v4_1")
    target_effect=_target_loo_effects(source,source_results); _both(target_effect,root/"target_position_loo_effects_v4_1")
    single={f"single_{h}":source_results[f"single_{h}"] for h in [20,60,120,180,250]}
    rcorr,single_net,single_pre=return_correlations(single,settings.section("run")["sample_split"]); _both(rcorr,root/"independent_return_correlations_v4_1")
    sector_corr,longshort_corr=_sector_direction_correlations(single,settings.section("run")["sample_split"]); _both(sector_corr,root/"sector_return_correlations_v4_1"); _both(longshort_corr,root/"long_short_return_correlations_v4_1")

    # Strategy sleeves, normal and fixed-3 tick.
    sleeve_results={}; internal_all=[]
    for name,horizons in settings.section("v4_1_research")["sleeves"].items():
        by_h={int(h):signals[f"single_{h}"] for h in horizons}; combined=_combine_signals(by_h)
        for code,suffix in [("C3",""),("C7","_fixed_3tick")]:
            label=f"strategy_sleeve_{name}_equal_risk{suffix}"; sc=ScenarioV41(label,"03_sleeve",COST_SPECS[code]); engine=SleeveEngineV41(settings,data,by_h,combined,fees); result=engine.run_v4_1(sc); run_count+=1
            internal=pd.DataFrame(engine.internal_target_rows); internal["strategy"]=label; internal_all.append(internal); _save_result(root/sc.name,result,combined,internal); sleeve_results[label]=result
    internal=pd.concat(internal_all,ignore_index=True); _both(internal,root/"sleeve_internal_targets_v4_1")
    _both(_sleeve_risk_summary(internal),root/"sleeve_risk_contribution_v4_1")
    sleeve_metrics=pd.DataFrame([row for label,result in sleeve_results.items() for row in _result_period_metrics(label,"C3" if "fixed" not in label else "C7",result,settings)]); _both(sleeve_metrics,root/"sleeve_metrics_v4_1")
    netting=_sleeve_netting(internal,sleeve_results,data.bars); _both(netting,root/"sleeve_netting_v4_1")
    sleeve_details=_sleeve_detail_tables(sleeve_results,settings); 
    for name,frame in sleeve_details.items(): _both(frame,root/name)

    # Diversification comparisons.
    div=[]; split=pd.Timestamp(settings.section("run")["sample_split"])
    combos=settings.section("v4_research")["combinations"]
    compare={"fast":["multi_fast_raw","multi_fast_scaled","strategy_sleeve_fast_equal_risk"],"all":["multi_all_raw","multi_all_scaled","strategy_sleeve_all_equal_risk"],"slow":["multi_slow_raw","multi_slow_scaled","strategy_sleeve_slow_equal_risk"]}
    all_results={**source_results,**sleeve_results}
    for family,labels in compare.items():
      comps=single_net[[f"single_{h}" for h in combos[family]]]
      for phase,mask in [("full",slice(None)),("insample",comps.index<split),("validation",comps.index>=split)]:
        c=comps if phase=="full" else comps.loc[mask]
        for label in labels: div.append(diversification_metrics(c,returns_from_result(all_results[label]),label,phase))
    _both(pd.DataFrame(div),root/"diversification_metrics_v4_1")

    # Joint 21-strategy bootstrap.
    base21={"reference_v3_252":source_results["reference_v3_252"],**{x:source_results[x] for x in candidates},**{k:v for k,v in sleeve_results.items() if "fixed" not in k}}
    if len(base21)!=21: raise AssertionError(f"bootstrap strategy count {len(base21)} !=21")
    net=pd.concat({k:returns_from_result(v,False) for k,v in base21.items()},axis=1); pre=pd.concat({k:returns_from_result(v,True) for k,v in base21.items()},axis=1)
    validate_bootstrap_inputs(net,pre,list(base21))
    b=settings.section("v4_1_research")["bootstrap"]; draws,blocks,ranks=moving_block_bootstrap(net,pre,settings.section("run")["sample_split"],int(b["seed"]),int(b["block_length"]),int(b["repetitions"])); summary,paired,paired_summary,stability,bootstrap_winners=bootstrap_summaries(draws,ranks)
    point_winners=_point_winner_stability(net,pre,ranks)
    _both(draws,root/"bootstrap_strategy_draws_v4_1"); _both(blocks,root/"bootstrap_block_draws_v4_1"); _both(summary,root/"bootstrap_strategy_summary_v4_1"); _both(paired,root/"bootstrap_paired_differences_v4_1"); _both(stability,root/"bootstrap_rank_stability_v4_1"); _both(ranks,root/"bootstrap_ranks_full_v4_1")
    _both(paired_summary,root/"bootstrap_paired_summary_v4_1"); _both(bootstrap_winners,root/"bootstrap_mean_winner_v4_1"); _both(point_winners,root/"bootstrap_point_winner_stability_v4_1")

    if run_count!=int(settings.section("v4_1_research")["maximum_new_engine_runs"]): raise AssertionError(f"registered run count mismatch: {run_count}")
    account=_accounting(all_results|{f"{a}_{c}":r for (a,c),r in matrix_results.items()},float(settings.section("run")["initial_capital"])); _both(account,root/"accounting_reconciliation_v4_1")
    if not account.passed.all(): raise AssertionError("accounting reconciliation failed")
    execution_results=all_results|{f"{a}_{c}":r for (a,c),r in matrix_results.items()}
    rebalance,margin=_execution_stats(execution_results); _both(rebalance,root/"rebalance_buffer_statistics_v4_1"); _both(margin,root/"margin_leverage_v4_1")
    _both(_version_comparison(project,source_results,sleeve_results,settings),root/"v3_v4_v4_1_comparison")
    registry=pd.DataFrame([{"stage":"gate","new_runs":4},{"stage":"same_path","new_runs":0},{"stage":"cost_counterfactual","new_runs":43},{"stage":"sleeve","new_runs":6},{"stage":"total","new_runs":run_count}]); _both(registry,root/"engine_run_count_v4_1")
    write_json({"status":"complete","version":"v4_1","new_engine_runs":run_count,"bootstrap_strategies":21,"bootstrap_repetitions":2000,"v2_v3_v4_modified":False},root/"manifest.json")
    from .reports_v4_1 import write_reports_v4_1
    write_reports_v4_1(settings,root); _trace(root)
    return root


def _combine_signals(by_h):
    first=next(iter(by_h.values())); dirs=pd.concat([b.directions.set_index(["date","instrument"])["direction"] for b in by_h.values()],axis=1).sum(axis=1).apply(np.sign).astype(int).rename("direction").reset_index(); meta=first.directions[["instrument","sector"]].drop_duplicates(); dirs=dirs.merge(meta,on="instrument"); dirs["signal_date"]=dirs.date.map(first.directions.drop_duplicates("date").set_index("date").signal_date); dirs=dirs[["date","signal_date","instrument","sector","direction"]]
    sels=pd.concat([b.selections for b in by_h.values()],ignore_index=True).drop_duplicates(); scores=pd.concat([b.scores.set_index(["date","instrument"])["score"] for b in by_h.values()],axis=1).mean(axis=1).rename("score").reset_index()
    return SignalBundle(scores,first.daily_price_vol,first.eligibility,first.liquidity,sels,dirs,{"sleeve_horizons":list(by_h)})


def _load_result(path):
    frames={a:read_frame(path/f) for a,f in [("equity","daily_equity"),("positions","positions"),("targets","targets"),("orders","orders"),("fills","fills"),("rejections","rejections"),("pnl_by_instrument","pnl_by_instrument")]}; diag=json.loads((path/"diagnostics.json").read_text(encoding="utf-8")) if (path/"diagnostics.json").exists() else {}; return BacktestResult(scenario=type("S",(),{"name":path.name})(),diagnostics=diag,**frames)


def _save_result(path,result,signals,internal=None):
    for n,f in [("daily_equity",result.equity),("positions",result.positions),("targets",result.targets),("orders",result.orders),("fills",result.fills),("rejections",result.rejections),("pnl_by_instrument",result.pnl_by_instrument),("scores",signals.scores),("selections",signals.selections),("directions",signals.directions)]: _both(f,path/n)
    if internal is not None:_both(internal,path/"internal_targets")
    write_json(result.diagnostics,path/"diagnostics.json")
    scenario=result.scenario
    cost=getattr(scenario,"cost",None)
    write_json({"label":getattr(scenario,"label",getattr(scenario,"name",path.name)),"stage":getattr(scenario,"stage",None),"name":getattr(scenario,"name",path.name),"cost":vars(cost) if cost is not None else None},path/"scenario_parameters.json")


def _compare_gate(label,signals,result,source_path,old):
    rows=[]; pairs=[("forecast",signals.scores,read_frame(source_path/"scores"),["date","instrument"]),("selections",signals.selections,read_frame(source_path/"selections"),["signal_date","sector","instrument","role"]),("directions",signals.directions,read_frame(source_path/"directions"),["date","instrument"]),("equity",result.equity,old.equity,["date"]),("targets",result.targets,old.targets,["date","contract"]),("positions",result.positions,old.positions,["date","contract"]),("orders",result.orders,old.orders,["created_date","contract","quantity"]),("fills",result.fills,old.fills,["date","created_date","contract","segment_index"]),("pnl",result.pnl_by_instrument,old.pnl_by_instrument,["date","contract"])]
    for name,a,b,keys in pairs:
      common=[c for c in a if c in b and c!="scenario"]; a=a[common].sort_values([k for k in keys if k in common]).reset_index(drop=True); b=b[common].sort_values([k for k in keys if k in common]).reset_index(drop=True); numeric=[c for c in common if pd.api.types.is_numeric_dtype(a[c]) and not pd.api.types.is_bool_dtype(a[c])]; diff=max([float((a[c]-b[c]).abs().max()) for c in numeric]+[0]); non=all(a[c].equals(b[c]) for c in common if c not in numeric); rows.append({"strategy":label,"table":name,"new_rows":len(a),"old_rows":len(b),"max_numeric_diff":diff,"non_numeric_equal":non,"passed":len(a)==len(b) and diff<=.01 and non})
    new_turn=result.fills.traded_notional.sum()/result.equity.equity.mean()/(len(result.equity)/252); old_turn=old.fills.traded_notional.sum()/old.equity.equity.mean()/(len(old.equity)/252); rows.append({"strategy":label,"table":"turnover_and_ending_equity","new_rows":1,"old_rows":1,"max_numeric_diff":max(abs(new_turn-old_turn),abs(result.equity.equity.iloc[-1]-old.equity.equity.iloc[-1])),"non_numeric_equal":True,"passed":abs(new_turn-old_turn)<=1e-10 and abs(result.equity.equity.iloc[-1]-old.equity.equity.iloc[-1])<=.01}); return rows


def _result_period_metrics(label,code,result,settings):
    rows=[]; initial=float(settings.section("run")["initial_capital"]); split=pd.Timestamp(settings.section("run")["sample_split"]); fills=slippage_components(result.fills)
    for period,start,end in [("full",None,None),("insample",None,split-pd.Timedelta(days=1)),("validation",split,None)]:
      eq=result.equity; emask=pd.Series(True,index=eq.index); fmask=pd.Series(True,index=fills.index)
      if start is not None: emask&=eq.date>=start; fmask&=fills.date>=start
      if end is not None: emask&=eq.date<=end; fmask&=fills.date<=end
      sub=eq.loc[emask]; f=fills.loc[fmask]; m=metrics_from_equity(sub,initial); rows.append({"strategy":label,"cost_code":code,"period":period,**m,"commission":f.commission.sum(),"base_slippage":f.base_slippage_cost.sum(),"roll_slippage":f.roll_slippage_cost.sum(),"impact":f.impact_cost.sum(),"lots":f.quantity.abs().sum(),"traded_notional":f.traded_notional.sum(),"turnover":f.traded_notional.sum()/sub.equity.mean()/(len(sub)/252)})
    return rows


def _assert_cost_result(code,result):
    fills=result.fills
    if code=="C0" and (fills.commission.abs().sum()>1e-8 or fills.slippage_cost.abs().sum()>1e-8): raise AssertionError("C0 contains explicit cost")
    if code=="C1" and fills.slippage_cost.abs().sum()>1e-8: raise AssertionError("C1 contains slippage")
    if code in {"C6","C7"}:
        expected=float(COST_SPECS[code].fixed_ticks)
        if not np.allclose(fills.base_slippage_ticks,expected): raise AssertionError(f"{code} fixed tick mismatch")


def _cost_elasticity(matrix,settings):
    rows=[]
    for (strategy,period),g in matrix.groupby(["strategy","period"]):
      g=g.set_index("cost_code"); base=g.loc["C3"]
      for code in ["C0","C1","C2","C4","C5","C6","C7"]:
        x=g.loc[code]; rows.append({"strategy":strategy,"period":period,"comparison":f"{code}-C3","cagr_change":x["年化收益率"]-base["年化收益率"],"sharpe_change":x["夏普比率"]-base["夏普比率"],"max_drawdown_change":x["最大回撤"]-base["最大回撤"],"net_profit_change":x["净利润_元"]-base["净利润_元"]})
      total_improvement=g.loc["C0","净利润_元"]-base["净利润_元"]
      accounting_addback=base[["commission","base_slippage","roll_slippage","impact"]].sum()
      rows.append({"strategy":strategy,"period":period,"comparison":"C0-C3_accounting_vs_feedback","cagr_change":g.loc["C0","年化收益率"]-base["年化收益率"],"sharpe_change":g.loc["C0","夏普比率"]-base["夏普比率"],"max_drawdown_change":g.loc["C0","最大回撤"]-base["最大回撤"],"net_profit_change":total_improvement,"same_path_accounting_addback":accounting_addback,"equity_position_feedback_residual":total_improvement-accounting_addback})
      axis=[("C2",-1),("C3",0),("C4",1),("C5",2)]; vals=[(shift,g.loc[c,"净利润_元"]) for c,shift in axis]; cross="未达到"; estimate=np.nan
      for (x1,y1),(x2,y2) in zip(vals,vals[1:]):
        if y1*y2<=0: estimate=x1+(0-y1)*(x2-x1)/(y2-y1); cross="区间内穿越"; break
      rows.append({"strategy":strategy,"period":period,"comparison":"break_even_normal_tick_shift","cagr_change":np.nan,"sharpe_change":np.nan,"max_drawdown_change":np.nan,"net_profit_change":np.nan,"break_even_status":cross,"break_even_shift_ticks":estimate,"tested_lower":-1,"tested_upper":2})
      svals=[(shift,g.loc[c,"夏普比率"]) for c,shift in axis]; scross="未达到"; sestimate=np.nan
      for (x1,y1),(x2,y2) in zip(svals,svals[1:]):
        if y1*y2<=0: sestimate=x1+(0-y1)*(x2-x1)/(y2-y1); scross="区间内穿越"; break
      rows.append({"strategy":strategy,"period":period,"comparison":"break_even_sharpe_normal_tick_shift","cagr_change":np.nan,"sharpe_change":np.nan,"max_drawdown_change":np.nan,"net_profit_change":np.nan,"break_even_status":scross,"break_even_shift_ticks":sestimate,"tested_lower":-1,"tested_upper":2})
    return pd.DataFrame(rows)


def _target_loo_effects(source,full_results):
    rows=[]
    for d in source.glob("04_marginal_loo__*"):
      p=json.loads((d/"scenario_parameters.json").read_text(encoding="utf-8")); parent=p["parent_label"]; old=_load_result(d); full=full_results[parent]
      for phase,start,end in [("full",None,None),("insample",None,pd.Timestamp("2021-12-31")),("validation",pd.Timestamp("2022-01-01"),None)]:
        def val(r):
          t=r.targets; f=r.fills; e=r.equity
          if start is not None: t=t[t.date>=start]; f=f[f.date>=start]; e=e[e.date>=start]
          if end is not None: t=t[t.date<=end]; f=f[f.date<=end]; e=e[e.date<=end]
          return {"target_abs":t.buffered_target.abs().sum(),"fills_lots":f.quantity.abs().sum(),"cost":f.commission.sum()+f.slippage_cost.sum(),"net":e.net_pnl.sum(),"mdd":metrics_from_equity(e,1)["最大回撤"]}
        a,b=val(full),val(old); rows.append({"parent":parent,"omitted_horizon":p["omitted_horizon"],"phase":phase,**{f"change_{k}":a[k]-b[k] for k in a}})
    return pd.DataFrame(rows)


def _forecast_influence_summary(influence, selection_change):
    rows=[]
    groupings=[("full",["combo","version","horizon"]),("phase",["combo","version","horizon","phase"]),("year",["combo","version","horizon","year"]),("sector",["combo","version","horizon","sector"]),("instrument",["combo","version","horizon","instrument"])]
    for scope,keys in groupings:
        for values,g in influence.groupby(keys,dropna=False):
            if not isinstance(values,tuple): values=(values,)
            row={"scope":scope,**dict(zip(keys,values)),"common_observations":len(g),"mean_absolute_contribution_weight":g.absolute_contribution_weight.mean(),"sign_flip_frequency":g.sign_flip.mean(),"decisive_frequency":g.decisive.mean(),"all_same_sign_frequency":g.all_same_sign.mean(),"opposing_frequency":g.has_opposing.mean(),"mean_cancellation_ratio":g.cancellation_ratio.mean()}
            rows.append(row)
    result=pd.DataFrame(rows)
    selected=selection_change.groupby(["combo","version","omitted_horizon","phase","year","sector","role"],dropna=False).agg(selection_common_observations=("selection_changed","size"),selection_change_frequency=("selection_changed","mean")).reset_index()
    selected=selected.rename(columns={"omitted_horizon":"horizon"}); selected["scope"]="selection_detail"
    return pd.concat([result,selected],ignore_index=True,sort=False)


def _forecast_correlation_summary(detail):
    group=["basis","horizon1","horizon2","scope","slice"]
    rows=[]
    for keys,g in detail.groupby(group,dropna=False):
        row=dict(zip(group,keys)); row.update({"instrument_count":g.instrument.nunique(),"common_observations":g.n.sum()})
        for col in ["pearson","spearman","sign_agreement","near_zero_disagreement"]:
            for q,name in [(.10,"p10"),(.25,"p25"),(.50,"median"),(.75,"p75"),(.90,"p90")]: row[f"{col}_{name}"]=g[col].quantile(q)
        rows.append(row)
    # A separate sector aggregation preserves the required cross-instrument distribution.
    for keys,g in detail.groupby(["basis","horizon1","horizon2","scope","slice","sector"],dropna=False):
        row=dict(zip(["basis","horizon1","horizon2","scope","slice","sector"],keys)); row.update({"instrument_count":g.instrument.nunique(),"common_observations":g.n.sum()})
        for col in ["pearson","spearman","sign_agreement","near_zero_disagreement"]:
            for q,name in [(.10,"p10"),(.25,"p25"),(.50,"median"),(.75,"p75"),(.90,"p90")]: row[f"{col}_{name}"]=g[col].quantile(q)
        rows.append(row)
    return pd.DataFrame(rows)


def _point_winner_stability(net,pre,ranks):
    rows=[]; split=pd.Timestamp("2022-01-01")
    for basis,frame in [("net",net),("pre_cost",pre)]:
      for phase,sub in [("full",frame),("insample",frame[frame.index<split]),("validation",frame[frame.index>=split])]:
        point=pd.DataFrame({c:bootstrap_metrics(sub[c].to_numpy()) for c in sub}).T
        for metric in ["cagr","sharpe","max_drawdown","calmar"]:
          winner=point[metric].idxmax(); q=ranks[(ranks.phase.eq(phase))&(ranks.basis.eq(basis))&(ranks.metric.eq(metric))&(ranks.strategy.eq(winner))]
          rows.append({"phase":phase,"basis":basis,"metric":metric,"point_estimate_winner":winner,"point_estimate_value":point.at[winner,metric],"bootstrap_retains_point_winner_frequency":(q["rank"]==1).mean(),"multiple_comparison_note":"21个策略探索性比较，未做正式多重比较推断"})
    return pd.DataFrame(rows)


def _sector_direction_correlations(results,split):
    sector=[]; direction=[]
    for label,r in results.items():
      p=r.pnl_by_instrument.copy(); p.date=pd.to_datetime(p.date)
      previous=r.equity.set_index("date").equity.shift(1)
      previous.iloc[0]=r.equity.equity.iloc[0]-r.equity.net_pnl.iloc[0]
      for sec,g in p.groupby("sector"):
          pnl=g.groupby("date").net_pnl.sum(); sector.append((pnl/previous.reindex(pnl.index)).rename((sec,label)))
      for side,g in p.groupby("position_direction"):
          pnl=g.groupby("date").net_pnl.sum(); direction.append((pnl/previous.reindex(pnl.index)).rename((side,label)))
    def build(series,keyname):
      rows=[]; groups={k:pd.concat([s for s in series if s.name[0]==k],axis=1).set_axis([s.name[1] for s in series if s.name[0]==k],axis=1) for k in set(s.name[0] for s in series)}
      for k,f in groups.items():
        slices={"full":f,"insample":f[f.index<pd.Timestamp(split)],"validation":f[f.index>=pd.Timestamp(split)]}; slices.update({f"year_{year}":g for year,g in f.groupby(f.index.year)})
        for scope,sub in slices.items():
          for a,b in combinations(f.columns,2): rows.append({keyname:k,"scope":scope,"strategy1":a,"strategy2":b,"pearson":sub[a].corr(sub[b]),"spearman":sub[a].corr(sub[b],method="spearman"),"n":len(sub[[a,b]].dropna())})
      return pd.DataFrame(rows)
    return build(sector,"sector"),build(direction,"position_direction")


def _sleeve_netting(internal,results,bars=None):
    rows=[]
    for label,r in results.items():
      x=internal[internal.strategy.eq(label)&internal.contract.notna()].copy(); x["date"]=pd.to_datetime(x.date)
      all_dates=pd.Series(pd.to_datetime(internal.loc[internal.strategy.eq(label),"date"].unique())).sort_values()
      weekly_dates=set(all_dates.groupby(all_dates.dt.to_period("W-FRI")).max())
      x=x[x.date.isin(weekly_dates)]
      panel=x.pivot_table(index="date",columns=["horizon","contract"],values="internal_target",aggfunc="sum").reindex(sorted(weekly_dates)).fillna(0.0)
      gross=panel.diff().fillna(panel).abs().to_numpy().sum()
      by_contract=panel.T.groupby(level="contract").sum().T
      net=by_contract.diff().fillna(by_contract).abs().to_numpy().sum(); saved=max(gross-net,0); actual_lots=r.fills.quantity.abs().sum(); cost=r.fills.commission.sum()+r.fills.slippage_cost.sum(); perlot=cost/actual_lots if actual_lots else 0
      extra={}
      if bars is not None:
          value=bars[["date","ts_code","open","point_value"]].drop_duplicates(["date","ts_code"]).assign(date=lambda z:pd.to_datetime(z.date)); value["notional_per_lot"]=value.open.abs()*value.point_value
          lookup=value.set_index(["date","ts_code"]).notional_per_lot
          gross_levels=[]; net_levels=[]; gross_trade_notional=[]; net_trade_notional=[]
          delta=panel.diff().fillna(panel); ndelta=by_contract.diff().fillna(by_contract)
          for date in panel.index:
              gp=panel.loc[date]; gd=delta.loc[date]; npanel=by_contract.loc[date]; nd=ndelta.loc[date]
              gross_levels.append(sum(abs(q)*lookup.get((date,c),np.nan) for (h,c),q in gp.items() if q and np.isfinite(lookup.get((date,c),np.nan))))
              net_levels.append(sum(abs(q)*lookup.get((date,c),np.nan) for c,q in npanel.items() if q and np.isfinite(lookup.get((date,c),np.nan))))
              gross_trade_notional.append(sum(abs(q)*lookup.get((date,c),np.nan) for (h,c),q in gd.items() if q and np.isfinite(lookup.get((date,c),np.nan))))
              net_trade_notional.append(sum(abs(q)*lookup.get((date,c),np.nan) for c,q in nd.items() if q and np.isfinite(lookup.get((date,c),np.nan))))
          extra={"mean_gross_internal_target_notional":np.mean(gross_levels),"mean_netted_target_notional":np.mean(net_levels),"gross_internal_target_change_notional":np.sum(gross_trade_notional),"netted_target_change_notional":np.sum(net_trade_notional),"netting_saved_target_change_notional":max(np.sum(gross_trade_notional)-np.sum(net_trade_notional),0)}
      rows.append({"strategy":label,"mean_gross_internal_target_lots":panel.abs().sum(axis=1).mean(),"mean_netted_target_lots":by_contract.abs().sum(axis=1).mean(),"weekly_internal_target_change_lots":gross,"weekly_algebraic_netted_target_change_lots":net,"netting_saved_target_change_lots":saved,**extra,"actual_fill_lots_after_constraints_buffer":actual_lots,"actual_cost":cost,"proxy_virtual_cost_without_netting":gross*perlot,"proxy_cost_saved_by_netting":saved*perlot,"proxy_note":"仅按正常周度目标变化和实际每手平均成本估计；不含独立执行模拟，不进入账户"})
    return pd.DataFrame(rows)


def _sleeve_risk_summary(internal):
    frame=internal.copy(); frame["date"]=pd.to_datetime(frame.date)
    rows=[]
    for keys,g in frame.groupby(["strategy","horizon","sector"],dropna=False):
        daily=g.groupby("date").agg(allocated_risk=("allocated_annual_risk","sum"),internal_risk=("internal_annual_risk","sum"),unused=("unused_signal_share","all"))
        rows.append({"strategy":keys[0],"horizon":keys[1],"sector":keys[2],"observations":len(daily),"mean_nominal_allocated_annual_risk":daily.allocated_risk.mean(),"mean_internal_annual_risk":daily.internal_risk.mean(),"realized_internal_over_allocated":daily.internal_risk.sum()/daily.allocated_risk.sum() if daily.allocated_risk.sum() else np.nan,"unused_share_frequency":daily.unused.mean()})
    return pd.DataFrame(rows)


def _execution_stats(results):
    rebalance=[]; margin=[]
    for label,r in results.items():
        d=r.diagnostics
        rebalance.append({"strategy":label,"normal_rebalance_days":d.get("normal_rebalance_days",0),"non_rebalance_days":d.get("non_rebalance_days",0),"buffer_evaluations":d.get("buffer_evaluations",0),"buffer_holds":d.get("buffer_holds",0),"buffer_trades":d.get("buffer_trades",0),"buffer_hold_rate":d.get("buffer_holds",0)/max(d.get("buffer_evaluations",0),1),"emergency_trigger_days":d.get("emergency_vol_trigger_days",0),"emergency_reduction_days":d.get("emergency_vol_reduction_days",0),"forced_constraint_days":d.get("forced_constraint_days",0),"orders":len(r.orders),"fill_segments":len(r.fills)})
        e=r.equity; margin.append({"strategy":label,"mean_total_margin_utilization":e.margin_utilization.mean(),"max_total_margin_utilization":e.margin_utilization.max(),"mean_commodity_margin_utilization":e.commodity_margin_utilization.mean(),"max_commodity_margin_utilization":e.commodity_margin_utilization.max(),"mean_commodity_gross_leverage":e.commodity_gross_leverage.mean(),"max_commodity_gross_leverage":e.commodity_gross_leverage.max(),"mean_government_bond_gross_leverage":e.exempt_gross_leverage.mean(),"max_government_bond_gross_leverage":e.exempt_gross_leverage.max()})
    return pd.DataFrame(rebalance),pd.DataFrame(margin)


def _version_comparison(project,source_results,sleeve_results,settings):
    initial=float(settings.section("run")["initial_capital"]); rows=[]
    selected={"v3_reference":source_results["reference_v3_252"],"v4_challenger_single_180_skip5":source_results["single_180_skip5"],**{f"v4_1_{k}":v for k,v in sleeve_results.items() if "fixed" not in k}}
    for label,r in selected.items():
        for period,start,end in [("full",None,None),("insample",None,pd.Timestamp("2021-12-31")),("validation",pd.Timestamp("2022-01-01"),None)]:
            m=metrics_from_equity(r.equity,initial,start,end); f=r.fills
            if start is not None: f=f[f.date>=start]
            if end is not None: f=f[f.date<=end]
            rows.append({"方案":label,"阶段":period,**m,"总成本_元":f.commission.sum()+f.slippage_cost.sum(),"成交手数":f.quantity.abs().sum()})
    return pd.DataFrame(rows)


def _sleeve_detail_tables(results,settings):
    initial=float(settings.section("run")["initial_capital"]); split=settings.section("run")["sample_split"]; end=settings.section("run")["end"]
    contributions={k:pnl_contribution_v4(r,k,split) for k,r in results.items()}
    return {
        "sleeve_yearly_v4_1":pd.concat([yearly_performance_v4(r,k,initial,end) for k,r in results.items()]),
        "sleeve_rolling_v4_1":pd.concat([rolling_walk_forward_v4(r,k,initial) for k,r in results.items()]),
        "sleeve_robustness_v4_1":pd.concat([robustness_v4(r,k,initial,split) for k,r in results.items()]),
        "sleeve_contribution_v4_1":pd.concat(contributions.values()),
        "sleeve_concentration_v4_1":pd.concat([concentration_v4(r,k,contributions[k]) for k,r in results.items()]),
    }


def _accounting(results,initial):
    rows=[]
    for label,r in results.items():
      prev=r.equity.equity.shift().fillna(initial); checks={"daily_equity":(r.equity.equity-prev-r.equity.net_pnl).abs().max(),"ending":abs(r.equity.net_pnl.sum()-(r.equity.equity.iloc[-1]-initial)),"fees":abs(r.equity.fees.sum()-r.fills.commission.sum()),"instrument_pnl":abs(r.pnl_by_instrument.net_pnl.sum()-r.equity.net_pnl.sum())}
      for k,v in checks.items(): rows.append({"strategy":label,"check":k,"error":v,"tolerance":.01,"passed":v<=.01})
    return pd.DataFrame(rows)


def _both(df,base): base.parent.mkdir(parents=True,exist_ok=True); df.to_pickle(base.with_suffix(".pkl")); df.to_csv(base.with_suffix(".csv"),index=False,encoding="utf-8-sig")
def _tests(project,root):
    e=os.environ.copy(); e["PYTHONPATH"]=f"{project/'src'}{os.pathsep}{project/'tests'}"; p=subprocess.run([sys.executable,"-m","unittest","discover","-s","tests","-p","test_*.py","-v"],cwd=project,env=e,text=True,capture_output=True); (root/"test_results_v4_1.txt").write_text(p.stdout+p.stderr,encoding="utf-8");
    if p.returncode: raise RuntimeError("tests failed")
def _trace(root):
    rows=[]
    for p in root.rglob("*.pkl"): rows.append({"pickle":str(p.relative_to(root)),"csv":str(p.with_suffix('.csv').relative_to(root)),"paired":p.with_suffix('.csv').exists()})
    _both(pd.DataFrame(rows),root/"pickle_csv_traceability_v4_1")
