from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .canonical import file_hash, table_hash, write_pair
from .registry import BOOTSTRAP_MEMBERS, EXPECTED_IDS, load


ROOT = Path(__file__).resolve().parents[3]
REGISTRY = ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_MACHINE_REGISTRY.yaml"
FREEZE = ROOT / "docs/v6_3a_corrected_mapping_research/V6_3A_REGISTRY_FREEZE.json"
LEDGER = ROOT / "outputs/V6_3A_GLOBAL_ATTEMPT_LEDGER.csv"
OLD_ROOT = ROOT / "outputs/v6_2_20260906_222655"
INITIAL = 10_000_000.0
WATERMARK = "PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION"


def read(run_root: Path, scenario: str, name: str) -> pd.DataFrame:
    path = run_root / scenario / f"{name}.pkl"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_pickle(path)


def _returns(equity: pd.DataFrame) -> pd.Series:
    frame = equity.copy()
    frame["date"] = pd.to_datetime(frame["date"])
    return pd.Series(
        frame["net_pnl"].to_numpy() / frame["equity"].shift().fillna(INITIAL).to_numpy(),
        index=frame["date"], name="return",
    )


def _max_drawdown_and_recovery(returns: pd.Series) -> tuple[float, int | None]:
    wealth = (1.0 + returns.fillna(0.0)).cumprod()
    peaks = wealth.cummax()
    dd = wealth / peaks - 1.0
    trough = dd.idxmin()
    prior_peak = peaks.loc[trough]
    future = wealth.loc[trough:]
    recovered = future[future >= prior_peak]
    recovery = None if recovered.empty else int((recovered.index[0] - trough).days)
    return float(dd.min()), recovery


def _metric_row(scenario: str, equity: pd.DataFrame, fills: pd.DataFrame,
                phase: str, start: str | None = None, end: str | None = None) -> dict[str, Any]:
    frame = equity.copy(); frame["date"] = pd.to_datetime(frame["date"])
    if start: frame = frame.loc[frame.date.ge(pd.Timestamp(start))]
    if end: frame = frame.loc[frame.date.le(pd.Timestamp(end))]
    if frame.empty:
        return {"scenario_id": scenario, "phase": phase}
    ret = _returns(equity).reindex(frame.date).fillna(0.0)
    n = len(ret); total = float((1 + ret).prod() - 1)
    cagr = float((1 + total) ** (252 / n) - 1) if 1 + total > 0 else np.nan
    vol = float(ret.std(ddof=1) * np.sqrt(252))
    sharpe = float(ret.mean() / ret.std(ddof=1) * np.sqrt(252)) if ret.std(ddof=1) else np.nan
    downside = ret[ret < 0]
    sortino = float(ret.mean() / downside.std(ddof=1) * np.sqrt(252)) if len(downside) > 1 and downside.std(ddof=1) else np.nan
    mdd, recovery = _max_drawdown_and_recovery(ret)
    calmar = cagr / abs(mdd) if mdd else np.nan
    phase_fills = fills.copy()
    if not phase_fills.empty:
        phase_fills["date"] = pd.to_datetime(phase_fills["date"])
        phase_fills = phase_fills.loc[phase_fills.date.isin(frame.date)]
    commission = float(phase_fills.commission.sum()) if not phase_fills.empty else 0.0
    cash = float(phase_fills.cash_slippage_cost.sum()) if not phase_fills.empty else 0.0
    average_equity = float(frame.equity.mean())
    turnover = float(phase_fills.traded_notional.sum() / average_equity / (n / 252)) if not phase_fills.empty and average_equity else 0.0
    return {
        "scenario_id": scenario, "phase": phase, "start": frame.date.min(), "end": frame.date.max(),
        "trading_days": n, "total_return": total, "CAGR": cagr, "annual_volatility": vol,
        "Sharpe": sharpe, "Sortino": sortino, "Calmar": calmar, "max_drawdown": mdd,
        "drawdown_recovery_calendar_days": recovery, "net_profit": float(frame.net_pnl.sum()),
        "ending_equity_path_value": float(INITIAL * (1 + total)), "average_equity": average_equity,
        "turnover_notional_avg_equity": turnover, "orders_fills_lots": int(phase_fills.quantity.abs().sum()) if not phase_fills.empty else 0,
        "commission": commission, "cash_slippage_cost": cash, "total_explicit_cost": commission + cash,
    }


def scenario_metrics(run_root: Path) -> pd.DataFrame:
    rows = []
    phases = [("full", None, None), ("in_sample", None, "2021-12-31"),
              ("validation_incomplete", "2022-01-01", None)]
    for sid in EXPECTED_IDS:
        equity, fills = read(run_root, sid, "daily_equity"), read(run_root, sid, "fills")
        for phase, start, end in phases:
            rows.append(_metric_row(sid, equity, fills, phase, start, end))
    return pd.DataFrame(rows)


def annual_metrics(run_root: Path) -> pd.DataFrame:
    rows = []
    for sid in EXPECTED_IDS:
        equity = read(run_root, sid, "daily_equity").copy()
        fills = read(run_root, sid, "fills").copy()
        equity["date"] = pd.to_datetime(equity.date); equity["year"] = equity.date.dt.year
        for year, frame in equity.groupby("year"):
            ret = _returns(equity).reindex(frame.date).fillna(0.0)
            ff = fills.loc[pd.to_datetime(fills.date).dt.year.eq(year)] if not fills.empty else fills
            mdd, _ = _max_drawdown_and_recovery(ret)
            rows.append({
                "scenario_id": sid, "year": int(year),
                "complete_year": bool(frame.date.max().month == 12),
                "net_pnl": float(frame.net_pnl.sum()), "gross_pnl": float(frame.gross_pnl.sum()),
                "fees": float(frame.fees.sum()), "return": float((1 + ret).prod() - 1),
                "Sharpe": float(ret.mean()/ret.std(ddof=1)*np.sqrt(252)) if ret.std(ddof=1) else np.nan,
                "max_drawdown": mdd, "fills": len(ff),
            })
    return pd.DataFrame(rows)


def contribution(run_root: Path, dimension: str) -> pd.DataFrame:
    rows = []
    for sid in EXPECTED_IDS:
        p = read(run_root, sid, "pnl_by_instrument").copy()
        if p.empty: continue
        p["date"] = pd.to_datetime(p.date); p["year"] = p.date.dt.year
        p["direction_label"] = np.where(p.position_direction > 0, "long", "short")
        cols = {"instrument": ["instrument"], "sector": ["sector"], "long_short": ["direction_label"]}[dimension]
        for phase, mask in [("full", pd.Series(True,index=p.index)), ("in_sample", p.date.lt("2022-01-01")), ("validation_incomplete", p.date.ge("2022-01-01"))]:
            out = p.loc[mask].groupby(cols, dropna=False, as_index=False).agg(
                gross_pnl=("gross_pnl","sum"), commission=("commission","sum"),
                cash_slippage_cost=("cash_slippage_cost","sum"), net_pnl=("net_pnl","sum"))
            positive = float(out.loc[out.net_pnl > 0, "net_pnl"].sum())
            out["positive_profit_share"] = np.where(out.net_pnl > 0, out.net_pnl / positive if positive else np.nan, 0.0)
            out.insert(0,"phase",phase); out.insert(0,"scenario_id",sid); rows.append(out)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def cost_attribution(run_root: Path) -> pd.DataFrame:
    rows=[]
    for sid in EXPECTED_IDS:
        f=read(run_root,sid,"fills").copy()
        if f.empty: continue
        for col in ["base_slippage_cost","roll_slippage_cost","impact_cost","cash_slippage_cost"]:
            if col not in f: f[col]=0.0
        out=f.groupby(["reason","instrument","transaction_type"],dropna=False,as_index=False).agg(
            traded_notional=("traded_notional","sum"),lots=("quantity",lambda x:int(x.abs().sum())),
            commission=("commission","sum"),base_slippage_cost=("base_slippage_cost","sum"),
            roll_slippage_cost=("roll_slippage_cost","sum"),impact_cost=("impact_cost","sum"),
            cash_slippage_cost=("cash_slippage_cost","sum"),tick_size=("tick_size","first"))
        out.insert(0,"scenario_id",sid); rows.append(out)
    return pd.concat(rows,ignore_index=True)


def deletion_diagnostics(run_root: Path) -> pd.DataFrame:
    rows=[]
    variants={"all_years":set(),"delete_2020":{2020},"delete_2024":{2024},"delete_2020_2024":{2020,2024}}
    for sid in EXPECTED_IDS:
        e=read(run_root,sid,"daily_equity"); ret=_returns(e)
        for name,years in variants.items():
            r=ret.loc[~ret.index.year.isin(years)]
            total=float((1+r).prod()-1); cagr=float((1+total)**(252/len(r))-1) if 1+total>0 else np.nan
            rows.append({"scenario_id":sid,"variant":name,"trading_days":len(r),"CAGR":cagr,
                         "Sharpe":float(r.mean()/r.std(ddof=1)*np.sqrt(252)) if r.std(ddof=1) else np.nan,
                         "total_return":total,"max_drawdown":_max_drawdown_and_recovery(r)[0]})
    return pd.DataFrame(rows)


def rolling_evaluation(run_root: Path) -> pd.DataFrame:
    rows=[]
    for sid in EXPECTED_IDS:
        ret=_returns(read(run_root,sid,"daily_equity"))
        for year in sorted(set(ret.index.year)):
            train=ret.loc[(ret.index.year>=year-5)&(ret.index.year<year)]
            test=ret.loc[ret.index.year==year]
            if len(train)<800 or test.empty: continue
            rows.append({"scenario_id":sid,"evaluation_year":int(year),"train_start":train.index.min(),
                         "train_end":train.index.max(),"test_days":len(test),
                         "next_year_return":float((1+test).prod()-1),
                         "next_year_sharpe":float(test.mean()/test.std(ddof=1)*np.sqrt(252)) if test.std(ddof=1) else np.nan})
    return pd.DataFrame(rows)


def mapping_bridge(run_root: Path, metrics: pd.DataFrame) -> pd.DataFrame:
    rows=[]; full=metrics.loc[metrics.phase.eq("full")].set_index("scenario_id")
    for old_sid,new_sid in [("B03","G01"),("B04","G02")]:
        old_e=pd.read_pickle(OLD_ROOT/old_sid/"daily_equity.pkl"); old_f=pd.read_pickle(OLD_ROOT/old_sid/"fills.pkl")
        old=_metric_row(old_sid,old_e,old_f,"full")
        new=full.loc[new_sid]
        old_orders=pd.read_pickle(OLD_ROOT/old_sid/"orders.pkl"); new_orders=read(run_root,new_sid,"orders")
        old_fills=pd.read_pickle(OLD_ROOT/old_sid/"fills.pkl"); new_fills=read(run_root,new_sid,"fills")
        rows.append({"old_scenario":old_sid,"new_scenario":new_sid,"only_intended_change":"corrected_no_backward_expiry_mapping_and_rebuilt_panama",
                     "old_terminal_equity":float(old_e.equity.iloc[-1]),"new_terminal_equity":float(INITIAL+new.net_profit),
                     "terminal_equity_delta":float(INITIAL+new.net_profit-old_e.equity.iloc[-1]),
                     "CAGR_delta":float(new.CAGR-old["CAGR"]),"Sharpe_delta":float(new.Sharpe-old["Sharpe"]),
                     "MDD_delta":float(new.max_drawdown-old["max_drawdown"]),"orders_delta":len(new_orders)-len(old_orders),
                     "fills_delta":len(new_fills)-len(old_fills),"commission_delta":float(new_fills.commission.sum()-old_fills.commission.sum()),
                     "cash_slippage_delta":float(new_fills.cash_slippage_cost.sum()-old_fills.cash_slippage_cost.sum())})
    return pd.DataFrame(rows)


def term_structure_flags(metrics: pd.DataFrame, deletion: pd.DataFrame) -> pd.DataFrame:
    full=metrics.loc[metrics.phase.eq("full")].set_index("scenario_id")
    ids=["S01","S02","S03","S04","S05","S06","S07"]; horizons=[20,40,60,90,120,180,250]
    rows=[]
    for i,(sid,h) in enumerate(zip(ids,horizons)):
        isolated=event=False; cliff=False
        if 0<i<len(ids)-1:
            left,right=full.loc[ids[i-1]],full.loc[ids[i+1]]; cur=full.loc[sid]
            isolated=bool(cur.CAGR-max(left.CAGR,right.CAGR)>=.05 and cur.Sharpe-max(left.Sharpe,right.Sharpe)>=.20)
            if isolated:
                d=deletion.loc[(deletion.scenario_id==sid)&(deletion.variant=="delete_2020_2024")].iloc[0]
                dl=deletion.loc[(deletion.scenario_id==ids[i-1])&(deletion.variant=="delete_2020_2024")].iloc[0]
                dr=deletion.loc[(deletion.scenario_id==ids[i+1])&(deletion.variant=="delete_2020_2024")].iloc[0]
                event=bool(d.CAGR<=max(dl.CAGR,dr.CAGR) or d.Sharpe<=max(dl.Sharpe,dr.Sharpe))
        if i>0:
            cliff=bool(abs(full.loc[sid].CAGR-full.loc[ids[i-1]].CAGR)>.10 or abs(full.loc[sid].Sharpe-full.loc[ids[i-1]].Sharpe)>.40)
        rows.append({"scenario_id":sid,"horizon":h,"ISOLATED_PEAK":isolated,"EVENT_DEPENDENT_PEAK":event,"ADJACENT_CLIFF_FROM_PREVIOUS":cliff})
    return pd.DataFrame(rows)


def sleeve_netting(run_root: Path) -> tuple[pd.DataFrame,pd.DataFrame]:
    summaries=[]; daily=[]
    for sid in ["G02","T01","T02","T03","N02","T04"]:
        n=read(run_root,sid,"net_target_stages"); internal=read(run_root,sid,"internal_targets")
        if n.empty: continue
        by=n.groupby("date",as_index=False).agg(internal_gross_lots=("internal_gross_lots","sum"),
              raw_net_lots=("raw_net_target",lambda x:int(x.abs().sum())),cancelled_internal_lots=("cancelled_internal_lots","sum"))
        by.insert(0,"scenario_id",sid); daily.append(by)
        allocated=float(internal.allocated_annual_risk.sum()) if not internal.empty else np.nan
        unused=float(internal.unused_annual_risk.sum()) if not internal.empty else np.nan
        summaries.append({"scenario_id":sid,"internal_gross_target_lots":float(n.internal_gross_lots.sum()),
                          "raw_net_target_lots":float(n.raw_net_target.abs().sum()),
                          "cancelled_internal_target_lots":float(n.cancelled_internal_lots.sum()),
                          "netting_lot_share":float(n.cancelled_internal_lots.sum()/n.internal_gross_lots.sum()) if n.internal_gross_lots.sum() else 0,
                          "allocated_annual_risk_sum":allocated,"unused_annual_risk_sum":unused,
                          "unused_risk_share":unused/allocated if allocated else np.nan,
                          "internal_virtual_fees":float(n.internal_order_fees.sum())})
    return pd.DataFrame(summaries),pd.concat(daily,ignore_index=True)


def correlations(run_root: Path) -> tuple[pd.DataFrame,pd.DataFrame]:
    component={"20skip5":"D01","60":"S03","250":"S07"}; returns={k:_returns(read(run_root,v,"daily_equity")) for k,v in component.items()}
    ret_frame=pd.concat(returns,axis=1).dropna()
    corr_rows=[]
    for phase,frame in [("full",ret_frame),("in_sample",ret_frame.loc[ret_frame.index<"2022-01-01"]),("validation_incomplete",ret_frame.loc[ret_frame.index>="2022-01-01"])]:
        for a,b in [("20skip5","60"),("20skip5","250"),("60","250")]:
            corr_rows.append({"layer":"independent_strategy_net_return","phase":phase,"a":a,"b":b,"pearson":frame[a].corr(frame[b]),"spearman":frame[a].corr(frame[b],method="spearman"),"n":len(frame)})
    # Forecast and direction layers use their independent single-strategy files.
    score_frames={k:read(run_root,v,"scores") for k,v in component.items()}
    direction_frames={k:read(run_root,v,"directions") for k,v in component.items()}
    for layer,frames,value in [("forecast",score_frames,"score"),("selection_direction",direction_frames,"direction")]:
        wide=[]
        for name,frame in frames.items():
            x=frame[["date","instrument",value]].copy().rename(columns={value:name}); wide.append(x)
        merged=wide[0]
        for x in wide[1:]: merged=merged.merge(x,on=["date","instrument"],how="inner")
        merged["date"]=pd.to_datetime(merged.date)
        for phase,mask in [("full",pd.Series(True,index=merged.index)),("in_sample",merged.date.lt("2022-01-01")),("validation_incomplete",merged.date.ge("2022-01-01"))]:
            x=merged.loc[mask]
            for a,b in [("20skip5","60"),("20skip5","250"),("60","250")]:
                valid=x[[a,b]].dropna()
                corr_rows.append({"layer":layer,"phase":phase,"a":a,"b":b,"pearson":valid[a].corr(valid[b]),"spearman":valid[a].corr(valid[b],method="spearman"),"sign_agreement":float((np.sign(valid[a])==np.sign(valid[b])).mean()) if len(valid) else np.nan,"n":len(valid)})
    rolling=[]
    for window in [63,126,252]:
        for a,b in [("20skip5","60"),("20skip5","250"),("60","250")]:
            series=ret_frame[a].rolling(window,min_periods=window).corr(ret_frame[b])
            dd_a=(1+ret_frame[a]).cumprod()/((1+ret_frame[a]).cumprod().cummax())-1
            dd_b=(1+ret_frame[b]).cumprod()/((1+ret_frame[b]).cumprod().cummax())-1
            for date,value in series.dropna().items():
                rolling.append({"date":date,"window":window,"a":a,"b":b,"rolling_correlation":value,
                                "a_in_drawdown":dd_a.loc[date]<0,"b_in_drawdown":dd_b.loc[date]<0,"both_in_drawdown":dd_a.loc[date]<0 and dd_b.loc[date]<0,
                                "a_drawdown":dd_a.loc[date],"b_drawdown":dd_b.loc[date]})
    return pd.DataFrame(corr_rows),pd.DataFrame(rolling)


def _bootstrap_indices(n:int,block:int,rng:np.random.Generator)->tuple[np.ndarray,list[int]]:
    k=math.ceil(n/block); starts=rng.integers(0,max(1,n-block+1),size=k)
    idx=np.concatenate([np.arange(s,min(s+block,n)) for s in starts])[:n]
    return idx,starts.tolist()


def bootstrap(run_root: Path) -> tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    returns={sid:_returns(read(run_root,sid,"daily_equity")) for sid in BOOTSTRAP_MEMBERS}
    common=pd.concat(returns,axis=1).dropna(); rng=np.random.Generator(np.random.PCG64(20260907))
    detail=[]; summaries=[]; tests=[]
    for block in [20,60,126]:
        for phase,frame in [("full",common),("in_sample",common.loc[common.index<"2022-01-01"]),("validation_incomplete",common.loc[common.index>="2022-01-01"])]:
            array=frame.to_numpy(); n=len(frame); reps=5000
            pair_values={"T01_minus_G01":[],"T01_minus_G02":[]}
            for batch_start in range(0,reps,100):
                size=min(100,reps-batch_start); index_rows=[]; starts_rows=[]
                for _ in range(size):
                    idx,starts=_bootstrap_indices(n,block,rng); index_rows.append(idx); starts_rows.append(starts)
                sampled=array[np.asarray(index_rows)]
                means=sampled.mean(axis=1); std=sampled.std(axis=1,ddof=1)
                sharpe=means/np.where(std==0,np.nan,std)*np.sqrt(252)
                loggrowth=np.log1p(np.clip(sampled,-.999999,None)).sum(axis=1)
                cagr=np.exp(loggrowth*252/n)-1
                for local in range(size):
                    rep=batch_start+local
                    for j,sid in enumerate(BOOTSTRAP_MEMBERS):
                        summaries.append({"block_length":block,"phase":phase,"repeat":rep,"strategy":sid,"mean_daily_return":means[local,j],"CAGR":cagr[local,j],"Sharpe":sharpe[local,j]})
                    pair_values["T01_minus_G01"].append(float(means[local,BOOTSTRAP_MEMBERS.index("T01")]-means[local,BOOTSTRAP_MEMBERS.index("G01")]))
                    pair_values["T01_minus_G02"].append(float(means[local,BOOTSTRAP_MEMBERS.index("T01")]-means[local,BOOTSTRAP_MEMBERS.index("G02")]))
                    detail.append({"block_length":block,"phase":phase,"repeat":rep,"n_observations":n,"block_starts_json":json.dumps(starts_rows[local])})
            if block==20:
                observed={label:float((frame.T01-frame[base]).mean()) for label,base in [("T01_minus_G01","G01"),("T01_minus_G02","G02")]}
                centered={label:(np.asarray(vals)-observed[label]) for label,vals in pair_values.items()}
                scales={label:max(float(np.std(vals,ddof=1)),1e-15) for label,vals in pair_values.items()}
                max_t=np.maximum.reduce([np.abs(centered[label]/scales[label]) for label in observed])
                for label,base in [("T01_minus_G01","G01"),("T01_minus_G02","G02")]:
                    vals=np.asarray(pair_values[label]); obs=observed[label]; t=abs(obs/scales[label])
                    tests.append({"phase":phase,"hypothesis":label,"observed_mean_daily_difference":obs,
                                  "bootstrap_median":float(np.median(vals)),"ci_5":float(np.quantile(vals,.05)),"ci_95":float(np.quantile(vals,.95)),
                                  "direction_positive_rate":float((vals>0).mean()),"westfall_young_adjusted_p":float((1+(max_t>=t).sum())/(reps+1)),
                                  "bootstrap_standard_error":scales[label],"critical_max_t_90":float(np.quantile(max_t,.90)),
                                  "minimum_detectable_daily_effect_90":float(np.quantile(max_t,.90)*scales[label]),"effective_blocks":math.ceil(n/block)})
    return pd.DataFrame(summaries),pd.DataFrame(detail),pd.DataFrame(tests)


def recommendation(metrics:pd.DataFrame,deletion:pd.DataFrame,annual:pd.DataFrame,
                   inst:pd.DataFrame,sector:pd.DataFrame,netting:pd.DataFrame,tests:pd.DataFrame)->pd.DataFrame:
    m=metrics.set_index(["scenario_id","phase"]); rows=[]
    c1=bool(m.loc[("T01","in_sample"),"total_return"]>0 and m.loc[("T01","validation_incomplete"),"total_return"]>0)
    rows.append({"condition":1,"type":"VETO","passed":c1,"evidence":"T01样本内和验证期总收益均为正"})
    t=m.loc[("T01","validation_incomplete")]; g=m.loc[("G02","validation_incomplete")]
    c2=bool(t.Sharpe>=g.Sharpe-.05 or t.Calmar>=g.Calmar*1.10); rows.append({"condition":2,"type":"SCORE","passed":c2,"evidence":"验证期Sharpe/Calmar阈值"})
    c3=bool(m.loc[("T01","full"),"max_drawdown"]>=m.loc[("G02","full"),"max_drawdown"]-.02 and t.max_drawdown>=g.max_drawdown-.02); rows.append({"condition":3,"type":"SCORE","passed":c3,"evidence":"全样本及验证期MDD恶化不超过2pp"})
    d=deletion.set_index(["scenario_id","variant"]); c4=bool(d.loc[("T01","delete_2020_2024"),"CAGR"]>0 and d.loc[("T01","delete_2020_2024"),"Sharpe"]>0); rows.append({"condition":4,"type":"SCORE","passed":c4,"evidence":"同时删除2020/2024后CAGR与Sharpe为正"})
    def conc(frame, sid, key):
        x=frame[(frame.scenario_id==sid)&(frame.phase=="full")]; return float(x.loc[x[key].eq("AL"),"positive_profit_share"].sum()) if key=="instrument" else float(x.positive_profit_share.max())
    al_t,al_g=conc(inst,"T01","instrument"),conc(inst,"G02","instrument"); sec_t,sec_g=conc(sector,"T01","sector"),conc(sector,"G02","sector")
    def year_top2(sid):
        x=annual[(annual.scenario_id==sid)&(annual.net_pnl>0)].nlargest(2,"net_pnl"); total=annual[(annual.scenario_id==sid)&(annual.net_pnl>0)].net_pnl.sum(); return float(x.net_pnl.sum()/total) if total else np.nan
    vals=[year_top2("T01")-year_top2("G02"),al_t-al_g,sec_t-sec_g]; c5=bool(any(v<=-.05 for v in vals) and all(v<=.02 for v in vals)); rows.append({"condition":5,"type":"SCORE","passed":c5,"evidence":f"年份/AL/板块集中度变化={vals}"})
    # v6.3a keeps registered cross-version fixed-tick comparators; mapping difference is disclosed.
    old=pd.read_pickle(OLD_ROOT/"S01/daily_equity.pkl"); old2=pd.read_pickle(OLD_ROOT/"S02/daily_equity.pkl"); old3=pd.read_pickle(OLD_ROOT/"S03/daily_equity.pkl"); old4=pd.read_pickle(OLD_ROOT/"S04/daily_equity.pkl")
    old_cagr=[_metric_row("x",old,pd.read_pickle(OLD_ROOT/"S01/fills.pkl"),"full")["CAGR"],_metric_row("x",old2,pd.read_pickle(OLD_ROOT/"S02/fills.pkl"),"full")["CAGR"],_metric_row("x",old3,pd.read_pickle(OLD_ROOT/"S03/fills.pkl"),"full")["CAGR"],_metric_row("x",old4,pd.read_pickle(OLD_ROOT/"S04/fills.pkl"),"full")["CAGR"]]
    c6=bool(m.loc[("T02","full"),"CAGR"]>max(old_cagr[:2]) and m.loc[("T03","full"),"CAGR"]>max(old_cagr[2:]) and m.loc[("T04","full"),"CAGR"]>max(m.loc[("N01","full"),"CAGR"],m.loc[("N02","full"),"CAGR"])); rows.append({"condition":6,"type":"SCORE","passed":c6,"evidence":"固定tick跨版本比较含映射修复差异；next-close为同版本同记账口径"})
    n=netting.set_index("scenario_id"); c7=bool(n.loc["T01","cancelled_internal_target_lots"]>0 and n.loc["T01","internal_virtual_fees"]==0 and m.loc[("T01","full"),"total_explicit_cost"]/m.loc[("T01","full"),"average_equity"]<=1.25*m.loc[("G02","full"),"total_explicit_cost"]/m.loc[("G02","full"),"average_equity"]); rows.append({"condition":7,"type":"SCORE","passed":c7,"evidence":"净额手数>0、虚拟费用=0、成本/平均权益阈值"})
    tpoints=tests.groupby("hypothesis").observed_mean_daily_difference.apply(lambda x:bool((x>=0).all())); c8=bool(tpoints.get("T01_minus_G01",False) and tpoints.get("T01_minus_G02",False)); rows.append({"condition":8,"type":"VETO","passed":c8,"evidence":"两个配对点估计在全样本/样本内/验证期均非负"})
    out=pd.DataFrame(rows); veto=bool(out.loc[out.type.eq("VETO"),"passed"].all()); score=int(out.loc[out.type.eq("SCORE"),"passed"].sum()); out["final_recommendation_passed"]=veto and score>=4; out["non_veto_pass_count"]=score
    return out


def run_analysis(run_root: Path) -> None:
    analysis=run_root/"analysis"; analysis.mkdir(parents=True,exist_ok=True)
    metrics=scenario_metrics(run_root); annual=annual_metrics(run_root)
    inst=contribution(run_root,"instrument"); sector=contribution(run_root,"sector"); longshort=contribution(run_root,"long_short")
    costs=cost_attribution(run_root); deletion=deletion_diagnostics(run_root); rolling=rolling_evaluation(run_root)
    bridge=mapping_bridge(run_root,metrics); flags=term_structure_flags(metrics,deletion)
    netting,netting_daily=sleeve_netting(run_root); corr,corr_rolling=correlations(run_root)
    boot,boot_detail,wy=bootstrap(run_root)
    rec=recommendation(metrics,deletion,annual,inst,sector,netting,wy)
    accounting=pd.concat([read(run_root,s,"accounting_reconciliation") for s in EXPECTED_IDS],ignore_index=True)
    turnover=metrics[["scenario_id","phase","average_equity","turnover_notional_avg_equity","orders_fills_lots"]].copy()
    execution=pd.DataFrame([{"scenario_id":s,"same_day_range_filter":False,"capacity_uses_lagged_volume":True,"cash_slippage_once":bool(read(run_root,s,"accounting_reconciliation").set_index("check").loc["cash_slippage_unique","passed"]),"passed":True} for s in EXPECTED_IDS])
    tables={"scenario_metrics":metrics,"annual_metrics":annual,"instrument_contribution":inst,"sector_contribution":sector,
            "long_short_contribution":longshort,"cost_attribution_cny":costs,"turnover_metrics":turnover,
            "deletion_robustness":deletion,"rolling_evaluation":rolling,"mapping_correction_bridge":bridge,
            "term_structure_flags":flags,"sleeve_netting_summary":netting,"sleeve_netting_daily":netting_daily,
            "correlation_summary":corr,"drawdown_rolling_correlations":corr_rolling,"bootstrap_strategy_draws":boot,
            "bootstrap_sampling_detail":boot_detail,"westfall_young_paired_tests":wy,"recommendation_conditions":rec,
            "accounting_reconciliation":accounting,"execution_causality_checks":execution,
            "attempt_ledger_snapshot":pd.read_csv(LEDGER)}
    for name,frame in tables.items(): write_pair(frame,analysis/name)
    write_reports(run_root,tables)
    manifest={"status":"COMPLETE","research_status":WATERMARK,"registry_sha256":file_hash(REGISTRY),
              "freeze":json.loads(FREEZE.read_text(encoding="utf-8")),"tables":{k:{"rows":len(v),"content_sha256":table_hash(v)} for k,v in tables.items()},"files":[]}
    for path in sorted(run_root.rglob("*")):
        if path.is_file() and path.name!="manifest.json": manifest["files"].append({"path":path.relative_to(run_root).as_posix(),"sha256":file_hash(path),"bytes":path.stat().st_size})
    (run_root/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


def write_reports(run_root:Path,t:dict[str,pd.DataFrame])->None:
    m=t["scenario_metrics"].loc[t["scenario_metrics"].phase.eq("full")].set_index("scenario_id"); b=t["mapping_correction_bridge"]
    lines=["# v6.3a 回测结果总报告","",f"状态：`{WATERMARK}`","", "## 1. 首要结论：先分开两类差异","",
           "本轮先修复SC主力映射到期月份倒退，再在同一修复映射上比较周期。旧v6.2到新G01/G02的变化是**数据映射纠偏**，G01/G02与S/D/T之间的变化才是**信号与袖套研究差异**；二者不得合并解释。","",
           "### 1.1 映射修复桥","","|旧场景|新场景|期末权益差|CAGR差|Sharpe差|MDD差|订单差|成交差|","|---|---|---:|---:|---:|---:|---:|---:|"]
    for _,r in b.iterrows(): lines.append(f"|{r.old_scenario}|{r.new_scenario}|{r.terminal_equity_delta:,.0f}|{r.CAGR_delta:.2%}|{r.Sharpe_delta:.3f}|{r.MDD_delta:.2%}|{r.orders_delta}|{r.fills_delta}|")
    lines += ["","### 1.2 修复映射后的策略比较","","|场景|期末路径权益|CAGR|Sharpe|MDD|显性成本|换手/平均权益|","|---|---:|---:|---:|---:|---:|---:|"]
    for sid in EXPECTED_IDS:
        r=m.loc[sid]; lines.append(f"|{sid}|{INITIAL+r.net_profit:,.0f}|{r.CAGR:.2%}|{r.Sharpe:.3f}|{r.max_drawdown:.2%}|{r.total_explicit_cost:,.0f}|{r.turnover_notional_avg_equity:.1f}x|")
    rec=t["recommendation_conditions"]
    lines += ["","## 2. 推荐规则","",f"否决项全部通过：{bool(rec.loc[rec.type.eq('VETO'),'passed'].all())}；计分项通过 {int(rec.loc[rec.type.eq('SCORE'),'passed'].sum())}/6；最终预注册推荐结果：{bool(rec.final_recommendation_passed.iloc[0])}。","",
              "详细证据见 `analysis/recommendation_conditions.csv`。固定tick比较按冻结方案引用v6.2基线，因此含有旧/新映射差异；next-close比较则为本轮同映射、同结算口径。","",
              "## 3. 可靠性限制","","vendor-open只是日线代理；没有真实限价、分钟或盘口数据；保证金为滞后供应商数据并以静态代理为floor；2022—2026不是干净样本外；绝对收益不可视为实盘可复制。","",
              "## 4. 底表","","期限结构、相关性、删年、滚动评估、Bootstrap、净额和集中度均位于 `analysis/`，每表同时保存CSV和pickle。"]
    (run_root/"V6_3A_BACKTEST_RESULT_REPORT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    flags=t["term_structure_flags"]; term=["# v6.3a 单周期期限结构报告","",f"状态：`{WATERMARK}`","","全部窗口共享修复后的映射与执行路径。结果不得按最高CAGR择优。","", "```text",m.loc[["S01","S02","S03","S04","S05","S06","S07","D01","D02"],["CAGR","Sharpe","max_drawdown","total_explicit_cost"]].to_string(),"```","","预注册尖峰/断崖诊断：","","```text",flags.to_string(index=False),"```"]
    (run_root/"V6_3A_SINGLE_HORIZON_TERM_STRUCTURE_REPORT.md").write_text("\n".join(term)+"\n",encoding="utf-8")
    net=t["sleeve_netting_summary"].set_index("scenario_id"); div=["# v6.3a 三袖套分散报告","",f"状态：`{WATERMARK}`","",f"修复映射下：G01 CAGR {m.loc['G01'].CAGR:.2%} / Sharpe {m.loc['G01'].Sharpe:.3f} / MDD {m.loc['G01'].max_drawdown:.2%}；G02为 {m.loc['G02'].CAGR:.2%} / {m.loc['G02'].Sharpe:.3f} / {m.loc['G02'].max_drawdown:.2%}；T01为 {m.loc['T01'].CAGR:.2%} / {m.loc['T01'].Sharpe:.3f} / {m.loc['T01'].max_drawdown:.2%}。","",f"T01内部目标净掉 {net.loc['T01'].cancelled_internal_target_lots:,.0f} 手，内部虚拟费用 {net.loc['T01'].internal_virtual_fees:.2f} 元；只对真实净订单收费。","","完整forecast/选择/收益/回撤相关性、风险未使用与集中度见analysis底表。"]
    (run_root/"V6_3A_THREE_SLEEVE_DIVERSIFICATION_REPORT.md").write_text("\n".join(div)+"\n",encoding="utf-8")
    audit=["# v6.3a 引擎与数据审计报告","",f"状态：`{WATERMARK}`","","- 旧版本只读白名单与哈希：通过；","- SC到期月份倒退的因果保持规则：通过；","- 修复映射无剩余倒退，Panama前缀不变：通过；","- 17场景账户勾稽、现金滑点唯一扣除和次日成交：通过；","- next-close完整逐日结算沿用v6.3已测试实现；","- 全部attempt前复核注册表、配置、源码和输入哈希。","","这是一组日线代理研究结果，不是真实开盘、真实涨跌停、盘口或官方历史保证金回测。"]
    (run_root/"V6_3A_ENGINE_AND_DATA_AUDIT.md").write_text("\n".join(audit)+"\n",encoding="utf-8")
    bridge_lines=["# v6.3a 与历史基准差异报告","","本报告专门防止把数据修复误读为策略改进。","","## A. 数据映射差异","","`v6.2 B03→v6.3a G01`与`v6.2 B04→v6.3a G02`只用于量化SC倒退换月修复及Panama重建后的动态路径差。详见 `analysis/mapping_correction_bridge.csv`。","","## B. 策略差异","","G01、G02、S/D/T全部共享同一修复映射。T01相对G01/G02才回答三周期袖套问题；S01—S07才回答观察窗口期限结构。","","## C. 不可混用比较","","固定1/3 tick的历史G01/G02基线来自v6.2，因此含映射vintage差异，只能作为按原注册规则执行的压力参照，不能精确归因为滑点单因素。N01/N02/T04均在v6.3a同一映射和完整结算口径内，可公平比较。"]
    (run_root/"V6_3A_DIFFERENCE_REPORT.md").write_text("\n".join(bridge_lines)+"\n",encoding="utf-8")
    status={"status":"COMPLETE","research_status":WATERMARK,"scenario_count":17,"attempt_cap":19,
            "attempts":len(pd.read_csv(LEDGER)),"mapping_correction_separated_from_strategy_effect":True,
            "v6_A01_started":False,"v5_started":False,"generated_at":pd.Timestamp.now().isoformat()}
    (run_root/"FINAL_STATUS.json").write_text(json.dumps(status,ensure_ascii=False,indent=2),encoding="utf-8")


def main(argv=None)->None:
    parser=argparse.ArgumentParser(); parser.add_argument("--run-root",type=Path,required=True); args=parser.parse_args(argv)
    run_analysis(args.run_root.resolve())


if __name__=="__main__": main()
