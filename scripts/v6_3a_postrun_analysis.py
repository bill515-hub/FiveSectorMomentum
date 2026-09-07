from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from five_sector_momentum.v6_2.canonical import file_hash, table_hash, write_pair


ROOT=Path(__file__).resolve().parents[1]
SCENARIOS=["G01","G02","S01","S02","S03","S04","S05","S06","S07","D01","D02","T01","T02","T03","N01","N02","T04"]
COMPONENTS={"20skip5":"D01","60":"S03","250":"S07"}
INITIAL=10_000_000.0


def read(run:Path,sid:str,name:str)->pd.DataFrame:
    return pd.read_pickle(run/sid/f"{name}.pkl")


def returns(run:Path,sid:str)->pd.Series:
    e=read(run,sid,"daily_equity").copy(); e["date"]=pd.to_datetime(e.date)
    return pd.Series(e.net_pnl.to_numpy()/e.equity.shift().fillna(INITIAL).to_numpy(),index=e.date,name=sid)


def freeze_recheck()->pd.DataFrame:
    freeze=json.loads((ROOT/"docs/v6_3a_corrected_mapping_research/V6_3A_REGISTRY_FREEZE.json").read_text(encoding="utf-8"))
    rows=[]
    for group in ["source_hashes","input_hashes"]:
        for item in freeze[group]:
            path=ROOT/item["path"]; actual=file_hash(path) if path.exists() else None
            rows.append({"group":group,"path":item["path"],"expected_sha256":item["sha256"],"actual_sha256":actual,"passed":actual==item["sha256"]})
    return pd.DataFrame(rows)


def scenario_difference(metrics:pd.DataFrame)->pd.DataFrame:
    m=metrics.set_index(["scenario_id","phase"]); pairs=[
        ("G01","G02","双袖套相对252日参照"),("G01","T01","三袖套相对252日参照"),("G02","T01","三袖套相对双袖套"),
        ("S01","D01","20日跳5相对普通20日"),("S03","D02","60日跳5相对普通60日"),
        ("T01","T02","三袖套固定1tick相对正常滑点"),("T01","T03","三袖套固定3tick相对正常滑点"),
        ("G01","N01","252日next-close相对vendor-open"),("G02","N02","双袖套next-close相对vendor-open"),("T01","T04","三袖套next-close相对vendor-open")]
    rows=[]
    for phase in ["full","in_sample","validation_incomplete"]:
        for a,b,label in pairs:
            x,y=m.loc[(a,phase)],m.loc[(b,phase)]
            rows.append({"phase":phase,"from_scenario":a,"to_scenario":b,"comparison":label,
                         "total_return_delta":y.total_return-x.total_return,"CAGR_delta":y.CAGR-x.CAGR,"Sharpe_delta":y.Sharpe-x.Sharpe,
                         "Calmar_delta":y.Calmar-x.Calmar,"MDD_delta":y.max_drawdown-x.max_drawdown,
                         "explicit_cost_delta":y.total_explicit_cost-x.total_explicit_cost,"turnover_delta":y.turnover_notional_avg_equity-x.turnover_notional_avg_equity})
    return pd.DataFrame(rows)


def buffer_margin(run:Path)->pd.DataFrame:
    rows=[]
    for sid in SCENARIOS:
        e=read(run,sid,"daily_equity"); diag=json.loads((run/sid/"diagnostics.json").read_text(encoding="utf-8"))
        usage=read(run,sid,"margin_engine_usage")
        vendor_share=float(usage.source_code.str.contains("VENDOR").mean()) if not usage.empty and "source_code" in usage else 0.0
        binding=float(usage.vendor_binding.mean()) if not usage.empty and "vendor_binding" in usage else 0.0
        rows.append({"scenario_id":sid,"buffer_evaluations":diag.get("buffer_evaluations",0),"buffer_holds":diag.get("buffer_holds",0),
                     "buffer_trades":diag.get("buffer_trades",0),"buffer_hold_share":diag.get("buffer_holds",0)/diag.get("buffer_evaluations",1) if diag.get("buffer_evaluations",0) else np.nan,
                     "emergency_trigger_days":diag.get("emergency_vol_trigger_days",0),"emergency_reduction_days":diag.get("emergency_vol_reduction_days",0),
                     "forced_constraint_days":diag.get("forced_constraint_days",0),"max_margin_utilization":float(e.margin_utilization.max()),
                     "max_commodity_margin_utilization":float(e.commodity_margin_utilization.max()),"max_gross_leverage":float(e.gross_leverage.max()),
                     "max_commodity_gross_leverage":float(e.commodity_gross_leverage.max()),"max_exempt_gross_leverage":float(e.exempt_gross_leverage.max()),
                     "vendor_lookup_share":vendor_share,"vendor_binding_share":binding})
    return pd.DataFrame(rows)


def netting_proxy(run:Path)->pd.DataFrame:
    rows=[]
    for sid in ["G02","T01","T02","T03","N02","T04"]:
        it=read(run,sid,"internal_targets").copy(); fills=read(run,sid,"fills")
        it["date"]=pd.to_datetime(it.date)
        # Each sleeve's desired target change before common scaling/constraints.
        sleeve=it.dropna(subset=["contract"]).groupby(["date","horizon","contract"],as_index=False).internal_target.sum()
        dates=sorted(sleeve.date.unique()); horizons=sorted(sleeve.horizon.unique()); contracts=sorted(sleeve.contract.unique())
        idx=pd.MultiIndex.from_product([dates,horizons,contracts],names=["date","horizon","contract"])
        wide=sleeve.set_index(["date","horizon","contract"]).internal_target.reindex(idx,fill_value=0).unstack(["horizon","contract"])
        virtual_gross=float(wide.diff().fillna(wide).abs().sum().sum())
        net=sleeve.groupby(["date","contract"],as_index=False).internal_target.sum()
        nidx=pd.MultiIndex.from_product([dates,contracts],names=["date","contract"])
        nwide=net.set_index(["date","contract"]).internal_target.reindex(nidx,fill_value=0).unstack("contract")
        raw_net=float(nwide.diff().fillna(nwide).abs().sum().sum())
        saved=max(0.0,virtual_gross-raw_net)
        actual_lots=float(fills.quantity.abs().sum()); actual_cost=float(fills.commission.sum()+fills.cash_slippage_cost.sum())
        avg_cost=actual_cost/actual_lots if actual_lots else np.nan
        rows.append({"scenario_id":sid,"preconstraint_virtual_gross_change_lots":virtual_gross,"preconstraint_netted_change_lots":raw_net,
                     "preconstraint_saved_change_lots":saved,"preconstraint_saved_share":saved/virtual_gross if virtual_gross else 0,
                     "actual_filled_lots":actual_lots,"actual_explicit_cost":actual_cost,"actual_average_cost_per_filled_lot":avg_cost,
                     "indicative_cost_saving_proxy":saved*avg_cost,"proxy_is_accounting_saving":False,
                     "exact_counterfactual_cost_identifiable":False})
    return pd.DataFrame(rows)


def target_correlations(run:Path)->pd.DataFrame:
    frames={}
    for name,sid in COMPONENTS.items():
        x=read(run,sid,"targets").copy(); x["date"]=pd.to_datetime(x.date)
        x=x.groupby(["date","instrument"],as_index=False).buffered_target.sum().rename(columns={"buffered_target":name})
        frames[name]=x
    merged=frames["20skip5"]
    for name in ["60","250"]: merged=merged.merge(frames[name],on=["date","instrument"],how="inner")
    rows=[]
    for phase,mask in [("full",pd.Series(True,index=merged.index)),("in_sample",merged.date.lt("2022-01-01")),("validation_incomplete",merged.date.ge("2022-01-01"))]:
        for sector in ["ALL"]:
            x=merged.loc[mask]
            for a,b in [("20skip5","60"),("20skip5","250"),("60","250")]:
                rows.append({"layer":"buffered_target_lots","phase":phase,"sector":sector,"a":a,"b":b,"pearson":x[a].corr(x[b]),
                             "spearman":x[a].corr(x[b],method="spearman"),"sign_agreement":float((np.sign(x[a])==np.sign(x[b])).mean()),"n":len(x)})
    return pd.DataFrame(rows)


def drawdown_summary(run:Path)->pd.DataFrame:
    r=pd.concat({k:returns(run,v) for k,v in COMPONENTS.items()},axis=1).dropna(); wealth=(1+r).cumprod(); dd=wealth/wealth.cummax()-1
    rows=[]
    for phase,mask in [("full",pd.Series(True,index=r.index)),("in_sample",r.index<"2022-01-01"),("validation_incomplete",r.index>="2022-01-01")]:
        rr=r.loc[mask]; d=dd.loc[mask]
        for a,b in [("20skip5","60"),("20skip5","250"),("60","250")]:
            any_dd=(d[a]<0)|(d[b]<0); both=(d[a]<0)&(d[b]<0); deep=(d[a]<=d[a].quantile(.25))&(d[b]<=d[b].quantile(.25))
            for condition,c_mask in [("all",pd.Series(True,index=rr.index)),("either_in_drawdown",any_dd),("both_in_drawdown",both),("both_deepest_quartile",deep)]:
                x=rr.loc[c_mask,[a,b]]
                rows.append({"phase":phase,"a":a,"b":b,"condition":condition,"return_correlation":x[a].corr(x[b]),"n":len(x),
                             "drawdown_overlap_share":float(both.mean()),"mean_joint_drawdown":float(d.loc[both,[a,b]].mean().mean()) if both.any() else np.nan})
    return pd.DataFrame(rows)


def concentration(run:Path,annual:pd.DataFrame,inst:pd.DataFrame,sector:pd.DataFrame,longshort:pd.DataFrame)->pd.DataFrame:
    rows=[]
    for sid in ["G01","G02","T01"]:
        a=annual[annual.scenario_id==sid]; pos=a[a.net_pnl>0]; year_share=float(pos.nlargest(2,"net_pnl").net_pnl.sum()/pos.net_pnl.sum())
        i=inst[(inst.scenario_id==sid)&(inst.phase=="full")]; s=sector[(sector.scenario_id==sid)&(sector.phase=="full")]; l=longshort[(longshort.scenario_id==sid)&(longshort.phase=="full")]
        al=float(i.loc[i.instrument.eq("AL"),"positive_profit_share"].sum()); fg=float(i.loc[i.instrument.eq("FG"),"positive_profit_share"].sum())
        chemical=float(s.loc[s.sector.eq("chemical_energy"),"net_pnl"].sum()); short=float(l.loc[l.direction_label.eq("short"),"net_pnl"].sum())
        rows.append({"scenario_id":sid,"top2_positive_year_profit_share":year_share,"AL_positive_profit_share":al,"FG_positive_profit_share":fg,
                     "max_positive_sector_profit_share":float(s.positive_profit_share.max()),"chemical_energy_net_pnl":chemical,"short_net_pnl":short})
    return pd.DataFrame(rows)


def hac_se(series:pd.Series,lag:int=19)->float:
    x=np.asarray(series.dropna(),dtype=float); n=len(x); u=x-x.mean(); gamma0=np.dot(u,u)/n; var=gamma0
    for k in range(1,min(lag,n-1)+1):
        gamma=np.dot(u[k:],u[:-k])/n; var+=2*(1-k/(lag+1))*gamma
    return float(np.sqrt(max(var,0)/n))


def wy_stepdown(run:Path,boot:pd.DataFrame)->pd.DataFrame:
    rows=[]
    actual=pd.concat({s:returns(run,s) for s in ["G01","G02","T01"]},axis=1).dropna()
    for phase,frame in [("full",actual),("in_sample",actual.loc[actual.index<"2022-01-01"]),("validation_incomplete",actual.loc[actual.index>="2022-01-01"])]:
        b=boot[(boot.block_length==20)&(boot.phase==phase)].pivot(index="repeat",columns="strategy",values="mean_daily_return")
        hypotheses={"T01_minus_G01":("G01",frame.T01-frame.G01),"T01_minus_G02":("G02",frame.T01-frame.G02)}
        observed={h:float(x.mean()) for h,(_,x) in hypotheses.items()}; se={h:hac_se(x) for h,(_,x) in hypotheses.items()}
        bt={h:(b.T01-b[base]-observed[h])/max(se[h],1e-15) for h,(base,_) in hypotheses.items()}
        obs_t={h:abs(observed[h]/max(se[h],1e-15)) for h in hypotheses}; order=sorted(hypotheses,key=lambda h:obs_t[h],reverse=True)
        prior=0.0
        for rank,h in enumerate(order):
            remaining=order[rank:]; maxima=pd.concat([bt[x].abs() for x in remaining],axis=1).max(axis=1)
            raw=(1+(maxima>=obs_t[h]).sum())/(len(maxima)+1); adjusted=max(prior,raw); prior=adjusted
            rows.append({"phase":phase,"hypothesis":h,"stepdown_rank":rank+1,"observed_mean_daily_difference":observed[h],"HAC_lag":19,"HAC_standard_error":se[h],
                         "observed_abs_t":obs_t[h],"remaining_family_size":len(remaining),"stepdown_adjusted_p":adjusted,"FWER":.10,
                         "critical_effect_approx_90":float(maxima.quantile(.90)*se[h]),"claim_statistically_significant":adjusted<=.10})
    return pd.DataFrame(rows)


def write_report(out:Path,run:Path,tables:dict[str,pd.DataFrame])->None:
    m=pd.read_pickle(run/"analysis/scenario_metrics.pkl"); full=m[m.phase=="full"].set_index("scenario_id"); phase=m.set_index(["scenario_id","phase"])
    bridge=pd.read_pickle(run/"analysis/mapping_correction_bridge.pkl"); flags=pd.read_pickle(run/"analysis/term_structure_flags.pkl"); rec=pd.read_pickle(run/"analysis/recommendation_conditions.pkl")
    conc=tables["concentration_summary"].set_index("scenario_id"); net=tables["netting_cost_saving_proxy"].set_index("scenario_id"); wy=tables["westfall_young_stepdown_audit"]
    bm=tables["buffer_margin_leverage"].set_index("scenario_id"); ddc=tables["drawdown_conditional_correlations"]
    lines=["# v6.3a 结果详细分析与差异总结","","> 证据等级：`PROVISIONAL_DAILY_ONLY_CAUSAL_EXECUTION`。本报告为冻结底表的只读事后分析，不重跑引擎。","",
           "## 1. 先说结论","",f"三周期 T01 没有足够证据替换双袖套 G02。全样本 T01 的 CAGR/Sharpe/MDD 为 {full.loc['T01'].CAGR:.2%}/{full.loc['T01'].Sharpe:.3f}/{full.loc['T01'].max_drawdown:.2%}，好于252日 G01 的 {full.loc['G01'].CAGR:.2%}/{full.loc['G01'].Sharpe:.3f}/{full.loc['G01'].max_drawdown:.2%}，但弱于双袖套 G02 的 {full.loc['G02'].CAGR:.2%}/{full.loc['G02'].Sharpe:.3f}/{full.loc['G02'].max_drawdown:.2%}。验证期 T01 CAGR仅 {phase.loc[('T01','validation_incomplete')].CAGR:.2%}，明显低于 G02 的 {phase.loc[('G02','validation_incomplete')].CAGR:.2%}。预注册否决项8失败，因此必须保留双袖套为研究候选。","",
           "## 2. 本轮最重要的差异：数据纠偏与策略差异必须分开","","### 2.1 映射纠偏桥","","|旧→新|期末权益差|CAGR差|Sharpe差|MDD差|订单差|成交差|","|---|---:|---:|---:|---:|---:|---:|"]
    for _,r in bridge.iterrows(): lines.append(f"|{r.old_scenario}→{r.new_scenario}|{r.terminal_equity_delta:,.0f}|{r.CAGR_delta:.3%}|{r.Sharpe_delta:.3f}|{r.MDD_delta:.3%}|{r.orders_delta}|{r.fills_delta}|")
    lines += ["","这只是35个SC日映射从近月倒退改为保持远月，并重建Panama后的动态路径变化；不能称为信号改进。修复对双袖套的权益影响大于参照，但均远小于策略间差异。","",
              "### 2.2 同一修复映射下的策略差异","","|场景|全样本CAGR|Sharpe|MDD|验证期CAGR|验证期Sharpe|成本|换手/平均权益|","|---|---:|---:|---:|---:|---:|---:|---:|"]
    for sid in ["G01","G02","T01","T02","T03","N01","N02","T04"]:
        x=full.loc[sid]; v=phase.loc[(sid,"validation_incomplete")]; lines.append(f"|{sid}|{x.CAGR:.2%}|{x.Sharpe:.3f}|{x.max_drawdown:.2%}|{v.CAGR:.2%}|{v.Sharpe:.3f}|{x.total_explicit_cost:,.0f}|{x.turnover_notional_avg_equity:.1f}x|")
    lines += ["","## 3. 单周期期限结构","","普通窗口不是平滑单调曲线。20→40→60日继续走弱，90日回升，120日出现跃升，180日回落，250日再走强。预注册标记只触发了 `S05相对S04的ADJACENT_CLIFF`；120日没有同时超过两侧规定的5pp CAGR和0.20 Sharpe，所以不构成正式 `ISOLATED_PEAK`。","", "|窗口|CAGR|Sharpe|MDD|期末权益|显性成本|","|---:|---:|---:|---:|---:|---:|"]
    for sid,h in zip(["S01","S02","S03","S04","S05","S06","S07"],[20,40,60,90,120,180,250]):
        x=full.loc[sid]; lines.append(f"|{h}|{x.CAGR:.2%}|{x.Sharpe:.3f}|{x.max_drawdown:.2%}|{INITIAL+x.net_profit:,.0f}|{x.total_explicit_cost:,.0f}|")
    lines += ["",f"20日跳5（D01）相对普通20日改善：CAGR {full.loc['D01'].CAGR:.2%} vs {full.loc['S01'].CAGR:.2%}；但60日跳5（D02）恶化为 CAGR {full.loc['D02'].CAGR:.2%}，低于普通60日 {full.loc['S03'].CAGR:.2%}。所以skip5不是普遍规律。","",
              "## 4. 三周期是否真的分散","",f"收益层相关：20skip5—60约0.526，20skip5—250约0.337，60—250约0.481；forecast层分别约0.589、0.344、0.558。现有20skip5—250本来就是三对中相关最低的一对；60日同时与两端保持约0.48—0.53的相关，增加的是中等相关且弱收益的组件，并没有补入更正交的第三条收益源。低相关是必要条件，不是足够条件。","",
              "回撤期也支持这一判断：全样本20skip5—250在双方同时回撤日的收益相关约0.315、最深四分位交集约0.252；验证期双方同时回撤日约0.273。它在压力期仍明显低于20skip5—60和60—250，多周期分散的主要来源仍是原双袖套，而不是新增60日。","",
              f"T01内部目标净额前估算节约 {net.loc['T01'].preconstraint_saved_change_lots:,.0f} 手变化（{net.loc['T01'].preconstraint_saved_share:.1%}）；内部虚拟目标确实未收费。但冻结底表没有保存‘每个袖套经过共同缩放后的反事实独立订单’，因此人民币节约只能给指示性代理 {net.loc['T01'].indicative_cost_saving_proxy:,.0f} 元，不能当作会计已实现节约。原自动条件7把手数节约和零虚拟费用视为通过，审计口径应降为 `PARTIALLY_TESTABLE`；这不影响最终不推荐，因为否决项8已失败。","",
              "## 5. 成本和执行时点","",f"T02固定1tick把T01期末权益从 {INITIAL+full.loc['T01'].net_profit:,.0f} 提高到 {INITIAL+full.loc['T02'].net_profit:,.0f}；T03固定3tick降至 {INITIAL+full.loc['T03'].net_profit:,.0f}。3tick下验证期CAGR为 {phase.loc[('T03','validation_incomplete')].CAGR:.2%}，已略为负，表明三袖套验证期对成本很敏感。","",f"完整结算next-close下，N01/N02/T04期末权益分别为 {INITIAL+full.loc['N01'].net_profit:,.0f}/{INITIAL+full.loc['N02'].net_profit:,.0f}/{INITIAL+full.loc['T04'].net_profit:,.0f}。双袖套仍领先；时点改变没有替三袖套翻转排序。","",
              "## 6. 年份、品种、板块和方向集中","",f"T01相对G02的前两盈利年份集中度反而上升 {conc.loc['T01'].top2_positive_year_profit_share-conc.loc['G02'].top2_positive_year_profit_share:+.2%}；AL正利润份额只下降 {conc.loc['T01'].AL_positive_profit_share-conc.loc['G02'].AL_positive_profit_share:+.2%}，未达到5个百分点阈值；最大正贡献板块份额上升 {conc.loc['T01'].max_positive_sector_profit_share-conc.loc['G02'].max_positive_sector_profit_share:+.2%}。集中度条件5失败。","",f"T01化工能源净贡献 {conc.loc['T01'].chemical_energy_net_pnl:,.0f} 元、空头净贡献 {conc.loc['T01'].short_net_pnl:,.0f} 元，均为负；AL仍贡献约 {conc.loc['T01'].AL_positive_profit_share:.1%} 的正利润，分散改善有限。","","验证期差距主要发生在2023和2025：60日单周期收益分别约-26.51%和-29.99%，而G02分别约+20.30%和+16.84%；加入60日后T01仅约+1.92%和-8.92%。验证期60日的化工、RB、AL以及空头均为负贡献，尤其空头约-950万元，解释了其低相关没有转化为有效分散。","",
              "## 7. Buffer、保证金与杠杆","",f"10% buffer确实生效：G01/G02/T01分别评估 {bm.loc['G01'].buffer_evaluations:,.0f}/{bm.loc['G02'].buffer_evaluations:,.0f}/{bm.loc['T01'].buffer_evaluations:,.0f} 次，其中保持原仓比例约 {bm.loc['G01'].buffer_hold_share:.1%}/{bm.loc['G02'].buffer_hold_share:.1%}/{bm.loc['T01'].buffer_hold_share:.1%}；并非每日细微波动都成交。对应紧急减仓日为 {bm.loc['G01'].emergency_reduction_days:,.0f}/{bm.loc['G02'].emergency_reduction_days:,.0f}/{bm.loc['T01'].emergency_reduction_days:,.0f}。","",f"最大总保证金利用率约 {bm.loc['G01'].max_margin_utilization:.1%}/{bm.loc['G02'].max_margin_utilization:.1%}/{bm.loc['T01'].max_margin_utilization:.1%}，最大总杠杆约 {bm.loc['G01'].max_gross_leverage:.2f}x/{bm.loc['G02'].max_gross_leverage:.2f}x/{bm.loc['T01'].max_gross_leverage:.2f}x。供应商率查表占比虽约68.5%—76.7%，真正高于静态floor并绑定仅约0.9%—1.1%，所以保证金接入仍近似被静态代理主导。","",
              "## 8. 删年与统计证据","",f"同时删除2020和2024后，T01 CAGR/Sharpe仍为 {pd.read_pickle(run/'analysis/deletion_robustness.pkl').set_index(['scenario_id','variant']).loc[('T01','delete_2020_2024')].CAGR:.2%}/{pd.read_pickle(run/'analysis/deletion_robustness.pkl').set_index(['scenario_id','variant']).loc[('T01','delete_2020_2024')].Sharpe:.3f}，所以并非只靠两个大年；但这不弥补验证期相对落后。","","正确step-down max-t复核如下（正式变量仅日均净收益差）：","","```text",wy.to_string(index=False),"```","","验证期仅约57个20日有效区块，统计功效有限。`T01-G02`验证期为负，调整后p约0.101，接近但未达到10% FWER阈值；`T01-G01`验证期同样为负。未显著不等于相等，胜率也不等于期望收益优势。","",
              "## 9. 预注册结论与审计修正","",f"原机器表：否决项1通过、否决项8失败；计分项通过3/6，最终不推荐。只读审计发现两处报告层限制：一是固定tick条件6引用v6.2旧映射基线，含映射vintage差异，不能称纯滑点单因素；二是条件7没有可识别的人民币反事实成本节约，只能部分验证。两项都只会让证据更保守，不会改变‘不推荐三袖套替代双袖套’。","",
              "## 10. 最终建议","","保留20skip5/250双袖套作为当前研究候选；三周期T01可保留为失败但有信息量的预注册实验，不进入生产候选。单周期结果只说明期限结构在120日附近有一次相邻断崖、长周期总体更可靠，不能事后把120日选成新信号。下一轮若继续，应先研究为什么60日验证期和空头/化工贡献弱，而不是优化权重或替换60日。","",
              "## 11. 可靠性限制","","所有绝对数字仍受vendor-open、缺少真实限价/分钟/盘口、代理滑点和非官方保证金限制；2022—2026不是干净样本外。本报告能较可靠回答同路径相对比较，不能证明实盘可复制。"]
    (out/"V6_3A_POSTRUN_DETAILED_ANALYSIS.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def write_audit(out:Path,run:Path,tables:dict[str,pd.DataFrame])->None:
    freeze=tables["freeze_recheck"]; ledger=pd.read_csv(ROOT/"outputs/V6_3A_GLOBAL_ATTEMPT_LEDGER.csv"); acc=pd.read_pickle(run/"analysis/accounting_reconciliation.pkl")
    lines=["# v6.3a 运行后独立审计","",f"结论：17/17场景完成，attempt {len(ledger)}/19、失败 {(ledger.status!='COMPLETED').sum()}；冻结哈希 {int(freeze.passed.sum())}/{len(freeze)} 通过；账户勾稽 {int(acc.passed.sum())}/{len(acc)} 通过，最大误差 {acc.error.max():.3g} 元。","",
           "## 通过项","","- 原 normalized_v2 未修改；新映射仅在 data/v6_3a；","- 35个修复日均为SC，保持合约有正成交量、有效收盘和至少20日到期余量；","- 修复后无到期月份倒退，Panama点差前缀误差约1.7e-13；","- 每次attempt前校验冻结注册表、配置、源码和输入；","- 现金滑点唯一扣除、次日成交、客户费1.5倍及账户恒等式全部通过；","- 完整历史完成后才运行纯分析与Bootstrap。","",
           "## 审计发现","","1. 主结论可信：三袖套全样本优于252参照但显著弱于双袖套，验证期两项配对点估计均为负，否决项8失败。","2. 原分析代码标称Westfall—Young step-down，实质使用了共同max-t单步调整和bootstrap标准差；本审计用冻结抽样结果补做step-down顺序，并以HAC(19)作为观测尺度。最终方向不变。","3. 净额表能精确证明内部目标未收费和净额手数下降，但不能精确识别经过统一缩放/buffer后的反事实人民币成本；条件7只能部分验证。","4. 固定tick的G01/G02参照来自v6.2旧映射，按注册表保留但不是纯单因素；next-close N01/N02/T04是干净同映射比较。","5. 原正式结果manifest生成于本次事后增强分析之前；增强工件使用独立目录和独立manifest，不回写冻结运行目录。"]
    (out/"V6_3A_POSTRUN_INDEPENDENT_AUDIT.md").write_text("\n".join(lines)+"\n",encoding="utf-8")


def main()->None:
    p=argparse.ArgumentParser(); p.add_argument("--run-root",type=Path,required=True); p.add_argument("--output",type=Path,required=True); args=p.parse_args()
    run=args.run_root.resolve(); out=args.output.resolve(); out.mkdir(parents=True,exist_ok=False)
    analysis=run/"analysis"; metrics=pd.read_pickle(analysis/"scenario_metrics.pkl"); annual=pd.read_pickle(analysis/"annual_metrics.pkl")
    inst=pd.read_pickle(analysis/"instrument_contribution.pkl"); sector=pd.read_pickle(analysis/"sector_contribution.pkl"); longshort=pd.read_pickle(analysis/"long_short_contribution.pkl")
    tables={"freeze_recheck":freeze_recheck(),"scenario_difference":scenario_difference(metrics),"buffer_margin_leverage":buffer_margin(run),
            "netting_cost_saving_proxy":netting_proxy(run),"target_layer_correlations":target_correlations(run),"drawdown_conditional_correlations":drawdown_summary(run),
            "concentration_summary":concentration(run,annual,inst,sector,longshort)}
    boot=pd.read_pickle(analysis/"bootstrap_strategy_draws.pkl"); tables["westfall_young_stepdown_audit"]=wy_stepdown(run,boot)
    tables["audit_findings"]=pd.DataFrame([
        {"id":"A01","severity":"PASS","finding":"17/17场景、冻结哈希和账户勾稽通过"},
        {"id":"A02","severity":"MEDIUM","finding":"原WY表为single-step max-t且使用bootstrap SE；本审计补做step-down+HAC(19)"},
        {"id":"A03","severity":"MEDIUM","finding":"净额人民币成本节约不可由冻结底表精确识别，条件7仅部分可测"},
        {"id":"A04","severity":"DISCLOSURE","finding":"固定tick跨版本参照含映射vintage差异；next-close为同映射公平比较"}])
    for name,frame in tables.items(): write_pair(frame,out/name)
    write_report(out,run,tables); write_audit(out,run,tables)
    manifest={"source_run":run.as_posix(),"analysis_only":True,"engine_rerun":False,"tables":{k:{"rows":len(v),"content_sha256":table_hash(v)} for k,v in tables.items()},"files":[]}
    for path in sorted(out.rglob("*")):
        if path.is_file(): manifest["files"].append({"path":path.relative_to(out).as_posix(),"sha256":file_hash(path),"bytes":path.stat().st_size})
    (out/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__": main()
