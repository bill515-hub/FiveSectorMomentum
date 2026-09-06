from __future__ import annotations

from itertools import combinations
import math

import numpy as np
import pandas as pd

from .analytics_v4 import metrics_from_returns_v4
from .signals import _weekly_select
from .signals_v4 import aggregate_from_library, strict_equal_weight


def slippage_components(fills: pd.DataFrame) -> pd.DataFrame:
    frame = fills.copy()
    denominator = frame["total_slippage_ticks"].replace(0.0, np.nan)
    for source, target in [
        ("base_slippage_ticks", "base_slippage_cost"),
        ("roll_extra_ticks", "roll_slippage_cost"),
        ("impact_ticks", "impact_cost"),
    ]:
        frame[target] = (frame["slippage_cost"] * frame[source] / denominator).fillna(0.0)
    return frame


def returns_from_result(result, pre_cost: bool = False) -> pd.Series:
    equity = result.equity.sort_values("date")
    previous = equity["equity"].shift(1)
    previous.iloc[0] = equity["equity"].iloc[0] - equity["net_pnl"].iloc[0]
    pnl = equity["net_pnl"].copy()
    if pre_cost:
        slip = result.fills.groupby("date")["slippage_cost"].sum()
        pnl = pnl + equity["fees"] + equity["date"].map(slip).fillna(0.0)
    return pd.Series(pnl.to_numpy() / previous.to_numpy(), index=pd.DatetimeIndex(equity["date"]), name="return")


def same_path_cost_study(label: str, result, initial: float, split: str):
    equity = result.equity.sort_values("date").copy()
    fills = slippage_components(result.fills)
    daily_cost = fills.groupby("date").agg(
        commission=("commission", "sum"), base_slippage_cost=("base_slippage_cost", "sum"),
        roll_slippage_cost=("roll_slippage_cost", "sum"), impact_cost=("impact_cost", "sum"),
        slippage_cost=("slippage_cost", "sum"), lots=("quantity", lambda x: x.abs().sum()),
        traded_notional=("traded_notional", "sum"),
    )
    equity = equity.merge(daily_cost, left_on="date", right_index=True, how="left")
    cost_cols = ["commission", "base_slippage_cost", "roll_slippage_cost", "impact_cost", "slippage_cost", "lots", "traded_notional"]
    equity[cost_cols] = equity[cost_cols].fillna(0.0)
    equity["same_path_pre_cost_pnl"] = equity["net_pnl"] + equity["commission"] + equity["slippage_cost"]
    equity["same_path_pre_cost_equity"] = initial + equity["same_path_pre_cost_pnl"].cumsum()
    previous_net = equity["equity"].shift(1).fillna(initial)
    previous_pre = equity["same_path_pre_cost_equity"].shift(1).fillna(initial)
    equity["net_return"] = equity["net_pnl"] / previous_net
    equity["same_path_pre_cost_return"] = equity["same_path_pre_cost_pnl"] / previous_pre
    equity.insert(0, "strategy", label)
    periods = {"full": (None, None), "insample": (None, pd.Timestamp(split)-pd.Timedelta(days=1)), "validation": (pd.Timestamp(split), None)}
    rows=[]
    for period,(start,end) in periods.items():
        sub=equity
        if start is not None: sub=sub[sub.date>=start]
        if end is not None: sub=sub[sub.date<=end]
        net=metrics_from_returns_v4(sub.net_return)
        pre=metrics_from_returns_v4(sub.same_path_pre_cost_return)
        years=max(len(sub)/252,1e-12); avg_eq=float(sub.equity.mean())
        turnover=float(sub.traded_notional.sum()/avg_eq/years)
        positive_pre=float(sub.same_path_pre_cost_pnl.clip(lower=0).sum())
        row={"strategy":label,"period":period,"turnover":turnover,"lots":sub.lots.sum(),"traded_notional":sub.traded_notional.sum()}
        for prefix,m in [("net",net),("same_path_pre_cost",pre)]:
            for k,v in m.items(): row[f"{prefix}_{k}"]=v
        row.update({
            "commission_drag":sub.commission.sum(),"base_slippage_drag":sub.base_slippage_cost.sum(),
            "roll_slippage_drag":sub.roll_slippage_cost.sum(),"impact_drag":sub.impact_cost.sum(),
            "total_cost_drag":sub.commission.sum()+sub.slippage_cost.sum(),
            "cagr_drag_points":pre["年化收益率"]-net["年化收益率"],
            "total_cost_over_positive_pre_cost_profit":(sub.commission.sum()+sub.slippage_cost.sum())/positive_pre if positive_pre else np.nan,
            "pre_cost_cagr_per_turnover":pre["年化收益率"]/turnover if turnover else np.nan,
            "net_cagr_per_turnover":net["年化收益率"]/turnover if turnover else np.nan,
            "cost_per_lot":(sub.commission.sum()+sub.slippage_cost.sum())/sub.lots.sum() if sub.lots.sum() else np.nan,
            "cost_per_million_notional":(sub.commission.sum()+sub.slippage_cost.sum())/sub.traded_notional.sum()*1e6 if sub.traded_notional.sum() else np.nan,
        }); rows.append(row)
    annual=equity.groupby(equity.date.dt.year).agg(net_pnl=("net_pnl","sum"),same_path_pre_cost_pnl=("same_path_pre_cost_pnl","sum"),commission=("commission","sum"),slippage=("slippage_cost","sum")).reset_index(names="year")
    annual.insert(0,"strategy",label); annual["cost_turns_positive_to_negative"]=(annual.same_path_pre_cost_pnl>0)&(annual.net_pnl<0)
    return equity, pd.DataFrame(rows), annual


def cost_event_attribution(label: str, result, meta: pd.DataFrame) -> pd.DataFrame:
    fills=slippage_components(result.fills); sectors=meta.set_index("instrument")["sector"]
    fills["sector"]=fills.instrument.map(sectors); fills["year"]=pd.to_datetime(fills.date).dt.year
    fills["side"]=np.where(fills.quantity>0,"buy","sell")
    group_cols=["date","created_date","contract","order_quantity","attempt","reason"]
    types=fills.groupby(group_cols)["transaction_type"].transform(lambda x: "|".join(sorted(set(x))))
    fills["event_class"]=fills.reason
    fills.loc[types.str.contains("open")&types.str.contains("close"),"event_class"]="cross_zero_reversal"
    cross=sectors[sectors.isin(["agriculture","chemical_energy"])].index
    for (date,sector),g in fills[fills.instrument.isin(cross)].groupby(["date","sector"]):
        if g.instrument.nunique()>1 and g.transaction_type.str.startswith("close").any() and g.transaction_type.eq("open").any():
            fills.loc[g.index,"event_class"]="cross_section_switch"
    return fills.groupby(["event_class","year","sector","instrument","side"],as_index=False).agg(
        fill_segments=("quantity","size"),lots=("quantity",lambda x:x.abs().sum()),
        commission=("commission","sum"),base_slippage=("base_slippage_cost","sum"),
        roll_slippage=("roll_slippage_cost","sum"),impact=("impact_cost","sum"),
        traded_notional=("traded_notional","sum"),
    ).assign(strategy=label)


def weekly_forecast_influence(library, settings, meta):
    signal_dates=pd.DatetimeIndex(library.prices.groupby(library.prices.index.to_period("W-FRI")).apply(lambda x:x.index[-1]).values)
    split=pd.Timestamp(settings.section("run")["sample_split"]); detail=[]; selection=[]
    combos=settings.section("v4_research")["combinations"]
    for combo,horizons0 in combos.items():
        horizons=tuple(int(h) for h in horizons0)
        for version,source in [("raw",library.raw_regular),("scaled",library.scaled_regular)]:
            weighted={h:source[h]/len(horizons) for h in horizons}
            full=strict_equal_weight([source[h] for h in horizons])
            full_sel,_,_=_weekly_select(full,library.eligibility,meta,settings.section("signal"))
            for h in horizons:
                omitted=strict_equal_weight([source[j] for j in horizons if j!=h])
                omit_sel,_,_=_weekly_select(omitted,library.eligibility,meta,settings.section("signal"))
                for date in signal_dates:
                    if date not in full.index: continue
                    for instrument in full.columns:
                        vals=pd.Series({j:weighted[j].at[date,instrument] for j in horizons})
                        if vals.isna().any(): continue
                        denominator=vals.abs().sum(); f=full.at[date,instrument]; o=omitted.at[date,instrument]
                        sector=meta.set_index("instrument").at[instrument,"sector"]
                        detail.append({"combo":combo,"version":version,"date":date,"phase":"insample" if date<split else "validation","year":date.year,"sector":sector,"instrument":instrument,"horizon":h,"nominal_weight":1/len(horizons),"absolute_contribution_weight":abs(vals[h])/denominator if denominator else np.nan,"full_forecast":f,"omitted_forecast":o,"sign_flip":np.sign(f)!=np.sign(o),"decisive":np.sign(f)!=np.sign(o),"all_same_sign":len(set(np.sign(vals)))==1,"has_opposing":vals.min()<0<vals.max(),"cancellation_ratio":1-abs(vals.sum())/vals.abs().sum() if vals.abs().sum() else 0})
                fs=full_sel.merge(omit_sel,on=["signal_date","sector","role"],how="outer",suffixes=("_full","_omit"))
                fs["combo"]=combo; fs["version"]=version; fs["omitted_horizon"]=h
                fs["phase"]=np.where(pd.to_datetime(fs.signal_date)<split,"insample","validation")
                fs["year"]=pd.to_datetime(fs.signal_date).dt.year
                fs["selection_changed"]=fs.instrument_full.ne(fs.instrument_omit)
                selection.append(fs)
    return pd.DataFrame(detail),pd.concat(selection,ignore_index=True)


def forecast_pair_correlations(library, meta, split: str, zero_near: float):
    dates=pd.DatetimeIndex(library.prices.groupby(library.prices.index.to_period("W-FRI")).apply(lambda x:x.index[-1]).values)
    sector=meta.set_index("instrument")["sector"]; rows=[]
    for basis, source in [("raw", library.raw_regular), ("scaled", library.scaled_regular)]:
      for a,b in combinations(sorted(source),2):
        for instrument in library.prices.columns:
            pair=pd.concat([source[a][instrument],source[b][instrument]],axis=1,keys=["a","b"]).reindex(dates).dropna()
            pair["phase"]=np.where(pair.index<pd.Timestamp(split),"insample","validation"); pair["year"]=pair.index.year
            for scope,key,sub in [("full","full",pair)]+[("phase",str(k),g) for k,g in pair.groupby("phase")]+[("year",str(k),g) for k,g in pair.groupby("year")]:
                if len(sub)<3: continue
                rows.append({"basis":basis,"horizon1":a,"horizon2":b,"instrument":instrument,"sector":sector[instrument],"scope":scope,"slice":key,"n":len(sub),"pearson":sub.a.corr(sub.b),"spearman":sub.a.corr(sub.b,method="spearman"),"sign_agreement":(np.sign(sub.a)==np.sign(sub.b)).mean(),"near_zero_disagreement":(((sub.a.abs()<=zero_near)|(sub.b.abs()<=zero_near))&(np.sign(sub.a)!=np.sign(sub.b))).mean()})
    return pd.DataFrame(rows)


def selection_pair_overlap(library, meta, split: str):
    dates=pd.DatetimeIndex(library.prices.groupby(library.prices.index.to_period("W-FRI")).apply(lambda x:x.index[-1]).values); rows=[]
    m=meta.set_index("instrument")
    for basis, source in [("raw", library.raw_regular), ("scaled", library.scaled_regular)]:
      for a,b in combinations(sorted(source),2):
        for date in dates:
            for sector_name in ["agriculture","chemical_energy"]:
                members=list(m[m.sector.eq(sector_name)].index); eligible=library.eligibility.loc[date,members]
                pair=pd.concat([source[a].loc[date,members],source[b].loc[date,members]],axis=1,keys=["a","b"])[eligible].dropna()
                if len(pair)<2: continue
                wa,wb=pair.a.idxmax(),pair.b.idxmax(); la,lb=pair.a.idxmin(),pair.b.idxmin()
                sa={x for x in [wa if pair.a[wa]>0 else None,la if pair.a[la]<0 else None] if x}; sb={x for x in [wb if pair.b[wb]>0 else None,lb if pair.b[lb]<0 else None] if x}
                rows.append({"basis":basis,"horizon1":a,"horizon2":b,"date":date,"phase":"insample" if date<pd.Timestamp(split) else "validation","year":date.year,"sector":sector_name,"n":len(pair),"rank_spearman":pair.a.corr(pair.b,method="spearman"),"winner_same":wa==wb,"loser_same":la==lb,"jaccard":len(sa&sb)/len(sa|sb) if sa|sb else 1.0})
    return pd.DataFrame(rows)


def return_correlations(results: dict[str,object], split: str):
    net=pd.concat({k:returns_from_result(v,False) for k,v in results.items()},axis=1)
    pre=pd.concat({k:returns_from_result(v,True) for k,v in results.items()},axis=1)
    rows=[]
    for basis,frame in [("net",net),("pre_cost",pre)]:
        slices={"full":frame,"insample":frame[frame.index<pd.Timestamp(split)],"validation":frame[frame.index>=pd.Timestamp(split)]}
        slices.update({f"year_{y}":g for y,g in frame.groupby(frame.index.year)})
        tail=frame[frame.mean(axis=1)<=frame.mean(axis=1).quantile(.05)]; slices["tail_worst_5pct"]=tail
        for scope,sub in slices.items():
            for a,b in combinations(frame.columns,2):
                pair=sub[[a,b]].dropna()
                wealth=(1.0+pair).cumprod()
                in_drawdown=wealth.lt(wealth.cummax())
                union=(in_drawdown[a] | in_drawdown[b]).sum()
                overlap=(in_drawdown[a] & in_drawdown[b]).sum()/union if union else np.nan
                rows.append({"basis":basis,"scope":scope,"strategy1":a,"strategy2":b,"n":len(pair),"pearson":pair[a].corr(pair[b]),"spearman":pair[a].corr(pair[b],method="spearman"),"drawdown_overlap_jaccard":overlap,"both_in_drawdown_frequency":(in_drawdown[a]&in_drawdown[b]).mean()})
    return pd.DataFrame(rows),net,pre


def diversification_metrics(component_returns: pd.DataFrame, portfolio_returns: pd.Series, label: str, phase: str):
    joined=component_returns.join(portfolio_returns.rename("portfolio"),how="inner").dropna(); comp=joined[component_returns.columns]
    vols=comp.std(ddof=1)*np.sqrt(252); pvol=joined.portfolio.std(ddof=1)*np.sqrt(252)
    corr=comp.corr().to_numpy(); eig=np.linalg.eigvalsh(corr); effective=(eig.sum()**2)/(eig@eig)
    return {"strategy":label,"phase":phase,"n":len(joined),"diversification_ratio":vols.mean()/pvol if pvol else np.nan,"effective_eigenvalue_count":effective,"portfolio_vol_over_component_average":pvol/vols.mean(),"portfolio_vol":pvol,"average_component_vol":vols.mean()}


def validate_bootstrap_inputs(net: pd.DataFrame, pre: pd.DataFrame, expected_strategies: list[str]) -> None:
    if list(net.columns) != expected_strategies or list(pre.columns) != expected_strategies:
        raise AssertionError("bootstrap strategy identity/order mismatch")
    if not net.index.equals(pre.index) or not net.index.is_monotonic_increasing or net.index.has_duplicates:
        raise AssertionError("bootstrap account calendars are not identical and ordered")
    if net.isna().any().any() or pre.isna().any().any():
        raise AssertionError("missing account day; zero filling is forbidden")


def moving_block_bootstrap(net: pd.DataFrame, pre: pd.DataFrame, split: str, seed: int, block: int, reps: int):
    rng=np.random.default_rng(seed); draw_rows=[]; block_rows=[]
    phases={"full":net.index,"insample":net.index[net.index<pd.Timestamp(split)],"validation":net.index[net.index>=pd.Timestamp(split)]}
    for phase,index in phases.items():
        n=len(index); starts_max=n-block
        starts=rng.integers(0,starts_max+1,size=(reps,math.ceil(n/block)))
        for r in range(reps):
            pieces=[]
            for order,s in enumerate(starts[r]):
                length=min(block,n-len(pieces)); pieces.extend(range(s,s+length)); block_rows.append({"phase":phase,"repeat":r,"block_order":order,"start_position":int(s),"start_date":index[s],"length":length})
                if len(pieces)>=n: break
            idx=np.asarray(pieces[:n])
            for basis,frame in [("net",net.loc[index]),("pre_cost",pre.loc[index])]:
                sampled=frame.to_numpy()[idx]
                for col,strategy in enumerate(frame.columns):
                    m=bootstrap_metrics(sampled[:,col]); draw_rows.append({"phase":phase,"basis":basis,"repeat":r,"strategy":strategy,**m})
    draws=pd.DataFrame(draw_rows); blocks=pd.DataFrame(block_rows)
    rank=[]
    for keys,g in draws.groupby(["phase","basis","repeat"]):
        for metric,ascending in [("cagr",False),("sharpe",False),("max_drawdown",False),("calmar",False)]:
            ranks=g[metric].rank(method="min",ascending=ascending)
            for i,value in zip(g.index,ranks): rank.append({"phase":keys[0],"basis":keys[1],"repeat":keys[2],"strategy":g.at[i,"strategy"],"metric":metric,"rank":value})
    ranks=pd.DataFrame(rank)
    return draws,blocks,ranks


def bootstrap_metrics(x):
    x=np.asarray(x,float); wealth=np.cumprod(1+x); years=len(x)/252; cagr=wealth[-1]**(1/years)-1
    std=x.std(ddof=1); vol=std*np.sqrt(252); sharpe=x.mean()/std*np.sqrt(252) if std>0 else np.nan
    down=x[x<0]; ddv=np.sqrt(np.mean(down**2))*np.sqrt(252) if len(down) else np.nan; sortino=x.mean()*252/ddv if ddv>0 else np.nan
    dd=wealth/np.maximum.accumulate(wealth)-1; mdd=dd.min(); calmar=cagr/abs(mdd) if mdd<0 else np.nan
    return {"cagr":cagr,"annual_volatility":vol,"sharpe":sharpe,"sortino":sortino,"max_drawdown":mdd,"calmar":calmar,"cumulative_return":wealth[-1]-1}


def bootstrap_summaries(draws, ranks, references=("reference_v3_252","single_180_skip5")):
    metrics=["cagr","annual_volatility","sharpe","sortino","max_drawdown","calmar","cumulative_return"]
    rows=[]
    for keys,g in draws.groupby(["phase","basis","strategy"]):
        for metric in metrics:
            x=g[metric]; rows.append({"phase":keys[0],"basis":keys[1],"strategy":keys[2],"metric":metric,"mean":x.mean(),"median":x.median(),"std":x.std(),"q025":x.quantile(.025),"q05":x.quantile(.05),"q10":x.quantile(.10),"q25":x.quantile(.25),"q75":x.quantile(.75),"q90":x.quantile(.90),"q95":x.quantile(.95),"q975":x.quantile(.975),"positive_frequency":(x>0).mean()})
    paired=[]
    for ref in references:
        base=draws[draws.strategy.eq(ref)].set_index(["phase","basis","repeat"])
        for strategy in draws.strategy.unique():
            cand=draws[draws.strategy.eq(strategy)].set_index(["phase","basis","repeat"])
            for metric in ["cagr","sharpe","max_drawdown"]:
                d=(cand[metric]-base[metric]).rename("difference").reset_index(); d["strategy"]=strategy; d["reference"]=ref; d["metric"]=metric; paired.append(d)
    paired=pd.concat(paired,ignore_index=True)
    paired_summary=[]
    for keys,g in paired.groupby(["phase","basis","strategy","reference","metric"]):
        x=g.difference
        paired_summary.append({"phase":keys[0],"basis":keys[1],"strategy":keys[2],"reference":keys[3],"metric":keys[4],"mean_difference":x.mean(),"median_difference":x.median(),"positive_frequency":(x>0).mean(),"q025":x.quantile(.025),"q05":x.quantile(.05),"q95":x.quantile(.95),"q975":x.quantile(.975)})
    stability=ranks.groupby(["phase","basis","strategy","metric"])["rank"].agg(mean_rank="mean",median_rank="median",best_frequency=lambda x:(x==1).mean(),q10=lambda x:x.quantile(.1),q90=lambda x:x.quantile(.9)).reset_index()
    point=[]
    for (phase,basis),g in draws.groupby(["phase","basis"]):
        # The point-estimate winner is deliberately determined outside the resamples
        # by the caller and merged later; this table retains all resampled win rates.
        for metric in ["cagr","sharpe","max_drawdown","calmar"]:
            best=g.groupby("strategy")[metric].mean().idxmax()
            win=stability[(stability.phase.eq(phase))&(stability.basis.eq(basis))&(stability.metric.eq(metric))&(stability.strategy.eq(best))].best_frequency.iloc[0]
            point.append({"phase":phase,"basis":basis,"metric":metric,"bootstrap_mean_winner":best,"winner_retention_frequency":win,"note":"探索性：基于bootstrap均值，而非原样本点估计"})
    return pd.DataFrame(rows),paired,pd.DataFrame(paired_summary),stability,pd.DataFrame(point)
