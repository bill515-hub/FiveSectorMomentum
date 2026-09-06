"""Post-gate analysis; no parameter selection and no additional engine runs."""
from itertools import combinations
import math
import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr
from .analytics_v4_1 import returns_from_result, slippage_components
from .workflow_v4_2 import save
from .workflow_v4_1 import _execution_stats

FAST='single_20_skip5';SLOW='single_250';SLEEVE='strategy_sleeve_20skip5_250_equal_risk';STRESS=SLEEVE+'_fixed_3tick';REF='reference_v3_252'
PHASE_NAMES={'full':'全样本','insample':'样本内','validation':'验证期'}


def drawdowns(x):
    x=np.asarray(x,float)
    if not np.isfinite(x).all() or np.any(x<=-1):raise ValueError('Invalid or missing return')
    wealth=np.cumprod(1+x)
    return wealth/np.maximum.accumulate(np.r_[1.,wealth])[1:]-1


def metrics(x):
    x=np.asarray(x,float)
    if len(x)<2:return {k:np.nan for k in ['cagr','vol','sharpe','sortino','mdd','calmar','total_return','observations','longest_underwater']}
    dd=drawdowns(x);std=x.std(ddof=1);vol=std*np.sqrt(252);annual=x.mean()*252
    growth=np.prod(1+x);cagr=growth**(252/len(x))-1;mdd=dd.min()
    down=np.sqrt(np.mean(np.minimum(x,0)**2))*np.sqrt(252)
    longest=0;run=0
    for flag in dd<0:run=run+1 if flag else 0;longest=max(longest,run)
    return {'cagr':cagr,'vol':vol,'sharpe':annual/vol if vol>0 else np.nan,'sortino':annual/down if down>0 else np.nan,
            'mdd':mdd,'calmar':cagr/abs(mdd) if mdd<0 else np.nan,'total_return':growth-1,'observations':len(x),'longest_underwater':longest}


def event_table(series):
    wealth=np.r_[1.,np.cumprod(1+series.to_numpy())];peak=1.;peak_i=0;active=False;trough_i=0;rows=[]
    def date(i):return series.index[i-1] if i else pd.NaT
    for i in range(1,len(wealth)):
        if wealth[i]>=peak:
            if active:
                rows.append({'peak_date':date(peak_i),'trough_date':date(trough_i),'recovery_date':date(i),'peak_position':peak_i-1,
                             'trough_position':trough_i-1,'end_position':i-1,'depth':wealth[trough_i]/peak-1,
                             'peak_to_recovery_days':i-peak_i,'underwater_days':i-peak_i-1,'recovered':True})
            peak=wealth[i];peak_i=i;active=False
        else:
            if not active:active=True;trough_i=i
            elif wealth[i]<wealth[trough_i]:trough_i=i
    if active:
        rows.append({'peak_date':date(peak_i),'trough_date':date(trough_i),'recovery_date':pd.NaT,'peak_position':peak_i-1,
                     'trough_position':trough_i-1,'end_position':len(series)-1,'depth':wealth[trough_i]/peak-1,
                     'peak_to_recovery_days':len(series)-peak_i,'underwater_days':len(series)-peak_i,'recovered':False})
    return pd.DataFrame(rows)


def phase_slices(index,years=False):
    result={'full':np.ones(len(index),bool),'insample':index<pd.Timestamp('2022-01-01'),'validation':index>=pd.Timestamp('2022-01-01')}
    if years:result.update({str(year):index.year==year for year in sorted(set(index.year))})
    return result


def corr(x,y,method='pearson',minimum=20):
    x=np.asarray(x);y=np.asarray(y);valid=np.isfinite(x)&np.isfinite(y);x=x[valid];y=y[valid]
    if len(x)<minimum or np.std(x)==0 or np.std(y)==0:return np.nan
    if method=='spearman':return float(spearmanr(x,y).statistic)
    if method=='kendall':return float(kendalltau(x,y).statistic)
    return float(np.corrcoef(x,y)[0,1])


def conditions(a,b,da,db):
    result={'unconditional':np.ones(len(a),bool)}
    for name,level in [('any',0),('moderate',-.1),('deep',-.2)]:
        fa=da<0 if level==0 else da<=level;fb=db<0 if level==0 else db<=level
        for tag,mask in [('fast',fa),('slow',fb),('both',fa&fb),('either',fa|fb),('only_one',fa^fb)]:result[f'{name}_{tag}']=mask
    ew=(a+b)/2
    for q in [.05,.01]:result[f'worst_equal_weight_{q}']=ew<=np.quantile(ew,q)
    return result


def correlation_analysis(net,pre,root):
    unconditional=[];conditional=[];overlap=[];protect=[];events=[];event_protection=[];rolls=[];roll_summary=[];transitions=[];tails=[];worst=[]
    for basis,frame in [('net',net),('pre_cost_diagnostic',pre)]:
        for phase,mask in phase_slices(frame.index,True).items():
            sub=frame.loc[mask]
            for left,right in combinations(sub.columns,2):
                for method in ['pearson','spearman','kendall']:
                    unconditional.append({'basis':basis,'phase':phase,'left':left,'right':right,'method':method,'n':len(sub),'correlation':corr(sub[left],sub[right],method)})
            a=sub[FAST].to_numpy();b=sub[SLOW].to_numpy();da=drawdowns(a);db=drawdowns(b)
            for condition,selected in conditions(a,b,da,db).items():
                for method in ['pearson','spearman','kendall']:
                    conditional.append({'basis':basis,'phase':phase,'condition':condition,'method':method,'n':int(selected.sum()),'correlation':corr(a[selected],b[selected],method),'sufficient':int(selected.sum())>=20})
            for label,level in [('any',0),('moderate',-.1),('deep',-.2)]:
                fa=da<0 if level==0 else da<=level;fb=db<0 if level==0 else db<=level
                overlap.append({'basis':basis,'phase':phase,'threshold':label,'n':len(sub),'joint_days':int((fa&fb).sum()),'joint_fraction':float((fa&fb).mean()),'union_days':int((fa|fb).sum()),'jaccard':(fa&fb).sum()/(fa|fb).sum() if (fa|fb).any() else np.nan})
                for who,condition,other in [(SLOW,fb,a),(FAST,fa,b)]:
                    r=other[condition]
                    protect.append({'basis':basis,'phase':phase,'drawdown_strategy':who,'threshold':label,'n':len(r),'other_mean_daily':np.mean(r) if len(r) else np.nan,'other_compounded_conditional_return':np.prod(1+r)-1 if len(r) else np.nan,'other_positive_day_fraction':np.mean(r>0) if len(r) else np.nan})
            for q in [.05,.01]:
                fa=a<=np.quantile(a,q);fb=b<=np.quantile(b,q);joint=fa&fb
                tails.append({'basis':basis,'phase':phase,'q':q,'n':len(sub),'joint_days':int(joint.sum()),'co_crash_fraction':joint.mean(),'lower_tail_dependence':joint.mean()/q,
                              'fast_downside_beta_to_slow':np.cov(a[b<0],b[b<0],ddof=1)[0,1]/np.var(b[b<0],ddof=1) if (b<0).sum()>=20 and np.var(b[b<0])>0 else np.nan,
                              'slow_downside_beta_to_fast':np.cov(b[a<0],a[a<0],ddof=1)[0,1]/np.var(a[a<0],ddof=1) if (a<0).sum()>=20 and np.var(a[a<0])>0 else np.nan})
        for strategy in [FAST,SLOW,SLEEVE,STRESS,REF]:
            ev=event_table(frame[strategy])
            if ev.empty:continue
            ev.insert(0,'strategy',strategy);ev.insert(0,'basis',basis);ev['severity_rank']=ev.depth.rank(method='first').astype(int);events.append(ev)
            if strategy in [FAST,SLOW]:
                other=SLOW if strategy==FAST else FAST
                for row in ev.itertuples():
                    segment=frame[other].iloc[row.peak_position+1:row.trough_position+1]
                    mix=frame[[FAST,SLOW]].iloc[row.peak_position+1:row.trough_position+1].mean(axis=1)
                    event_protection.append({'basis':basis,'drawdown_strategy':strategy,'other_strategy':other,'peak_date':row.peak_date,'trough_date':row.trough_date,'source_depth':row.depth,'n':len(segment),'other_total_return':np.prod(1+segment)-1,'other_mdd':drawdowns(segment).min() if len(segment) else np.nan,'equal_weight_segment_return':np.prod(1+mix)-1})
        for window in [63,126,252]:
            series=frame[FAST].rolling(window,min_periods=window).corr(frame[SLOW]);valid=series.dropna()
            rolls.append(pd.DataFrame({'basis':basis,'date':series.index,'window':window,'correlation':series.values}))
            roll_summary.append({'basis':basis,'window':window,'n':len(valid),'mean':valid.mean(),'median':valid.median(),'p10':valid.quantile(.1),'p90':valid.quantile(.9),'minimum':valid.min(),'maximum':valid.max()})
            armed=False;low_date=None;i=0
            while i<len(valid):
                value=valid.iloc[i]
                if value<0:armed=True;low_date=valid.index[i]
                elif value>.5 and armed:
                    start=i
                    while i+1<len(valid) and valid.iloc[i+1]>.5:i+=1
                    transitions.append({'basis':basis,'window':window,'last_below_zero':low_date,'first_above_half':valid.index[start],'end_above_half':valid.index[i],'high_duration_days':i-start+1,'ongoing_at_end':i==len(valid)-1});armed=False
                i+=1
        for frequency in ['D','W-FRI','ME']:
            agg=frame if frequency=='D' else (1+frame).resample(frequency).prod()-1
            score=agg[[FAST,SLOW]].mean(axis=1)
            for date in score.nsmallest(10).index:
                row={'basis':basis,'frequency':frequency,'date':date,'equal_weight_return':score.loc[date]}
                row.update({col:agg.at[date,col] for col in [FAST,SLOW,SLEEVE,STRESS]});worst.append(row)
    frames={'return_correlation_matrices':pd.DataFrame(unconditional),'conditional_drawdown_correlations':pd.DataFrame(conditional),'drawdown_overlap':pd.DataFrame(overlap),'conditional_protection':pd.DataFrame(protect),'drawdown_events':pd.concat(events,ignore_index=True),'peak_trough_protection':pd.DataFrame(event_protection),'rolling_correlations':pd.concat(rolls,ignore_index=True),'rolling_correlation_summary':pd.DataFrame(roll_summary),'correlation_state_transitions':pd.DataFrame(transitions),'tail_risk':pd.DataFrame(tails),'joint_worst_periods':pd.DataFrame(worst)}
    for name,frame in frames.items():save(frame,root,name+'_v4_2')


def bootstrap_indices(n,reps,seed=20260902,block=20):
    if n<block:raise ValueError('Too few observations for registered block length')
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,n-block+1,size=(reps,math.ceil(n/block)))
    indices=(starts[:,:,None]+np.arange(block)).reshape(reps,-1)[:,:n]
    return starts,indices


def bootstrap_analysis(net,pre,root,reps=2000):
    draws=[];blocks=[];paired=[];condition_rows=[]
    ordered=[FAST,SLOW,SLEEVE,STRESS,REF,'single_20','single_60','single_120','single_180']
    rng=np.random.default_rng(20260902)
    for phase,mask in phase_slices(net.index).items():
        dates=net.index[mask];n=len(dates);starts=rng.integers(0,n-20+1,size=(reps,math.ceil(n/20)))
        for repeat in range(reps):
            idx=(starts[repeat,:,None]+np.arange(20)).ravel()[:n]
            for order,start in enumerate(starts[repeat]):
                length=min(20,n-order*20)
                blocks.append({'phase':phase,'repeat':repeat,'block_order':order,'start_position':int(start),'start_date':dates[start],'end_date':dates[start+length-1],'length':length})
            for basis,frame in [('net',net),('pre_cost_diagnostic',pre)]:
                sampled=frame.loc[mask,ordered].to_numpy()[idx];stats={}
                for col,strategy in enumerate(ordered):
                    m=metrics(sampled[:,col]);stats[strategy]=m
                    draws.append({'phase':phase,'basis':basis,'repeat':repeat,'strategy':strategy,**m})
                for reference in [SLOW,FAST,REF]:
                    for metric in ['cagr','sharpe','mdd','calmar','longest_underwater']:
                        paired.append({'phase':phase,'basis':basis,'repeat':repeat,'reference':reference,'metric':metric,'difference':stats[SLEEVE][metric]-stats[reference][metric]})
                a,b=sampled[:,0],sampled[:,1];da,db=drawdowns(a),drawdowns(b);ds=drawdowns(sampled[:,2]);base=corr(a,b)
                for condition,selected in conditions(a,b,da,db).items():
                    coefficient=corr(a[selected],b[selected]);condition_rows.append({'phase':phase,'basis':basis,'repeat':repeat,'statistic':condition+'_pearson_minus_unconditional','n':int(selected.sum()),'value':coefficient-base})
                for name,level in [('any',0),('moderate',-.1),('deep',-.2)]:
                    fa=da<0 if level==0 else da<=level;fb=db<0 if level==0 else db<=level;fs=ds<0 if level==0 else ds<=level
                    j=(fa&fb).sum()/(fa|fb).sum() if (fa|fb).any() else np.nan
                    js=(fs&fb).sum()/(fs|fb).sum() if (fs|fb).any() else np.nan
                    condition_rows.append({'phase':phase,'basis':basis,'repeat':repeat,'statistic':name+'_fast_slow_jaccard','n':n,'value':j})
                    condition_rows.append({'phase':phase,'basis':basis,'repeat':repeat,'statistic':name+'_sleeve_slow_minus_fast_slow_jaccard','n':n,'value':js-j})
            if (repeat+1)%500==0:print(f'BOOTSTRAP {phase} {repeat+1}/{reps}',flush=True)
    frames={'bootstrap_draws':pd.DataFrame(draws),'bootstrap_blocks':pd.DataFrame(blocks),'bootstrap_paired':pd.DataFrame(paired),'bootstrap_condition_draws':pd.DataFrame(condition_rows)}
    for name,frame in frames.items():save(frame,root,name+'_v4_2')
    calendars=[]
    for phase,mask in phase_slices(net.index).items():calendars.extend({'phase':phase,'position':i,'date':date} for i,date in enumerate(net.index[mask]))
    save(pd.DataFrame(calendars),root,'bootstrap_source_calendar_v4_2')
    summaries=[]
    for typ,frame,keys,value in [('paired',frames['bootstrap_paired'],['phase','basis','reference','metric'],'difference'),('conditions',frames['bootstrap_condition_draws'],['phase','basis','statistic'],'value')]:
        for group,g in frame.groupby(keys):
            x=g[value].dropna();summaries.append({'type':typ,**dict(zip(keys,group)),'valid_repeats':len(x),'mean':x.mean(),'median':x.median(),'q025':x.quantile(.025),'q05':x.quantile(.05),'q95':x.quantile(.95),'q975':x.quantile(.975),'probability_positive':(x>0).mean() if len(x) else np.nan})
    save(pd.DataFrame(summaries),root,'bootstrap_confidence_intervals_v4_2')


def performance_tables(net,pre,results,root):
    records=[];walk=[];equal=[];contributions=[];concentrations=[];costs=[]
    for strategy,r in results.items():
        eq=r.equity.set_index('date');f=slippage_components(r.fills)
        p=r.pnl_by_instrument.copy();p['year']=p.date.dt.year
        for phase,mask in phase_slices(net.index,True).items():
            for basis,wide in [('net',net),('pre_cost_diagnostic',pre)]:
                subset=wide.loc[mask,strategy]
                records.append({'strategy':strategy,'phase':phase,'basis':basis,'exclusion':'none','partial_year':phase=='2026',**metrics(subset)})
                if phase in ['full','insample','validation']:
                    for label,years in [('delete_2020',[2020]),('delete_2024',[2024]),('delete_both',[2020,2024])]:
                        records.append({'strategy':strategy,'phase':phase,'basis':basis,'exclusion':label,'partial_year':True,**metrics(subset.loc[~subset.index.year.isin(years)])})
            if phase in ['full','insample','validation']:
                dates=net.index[mask];g=p.loc[p.date.isin(dates)];fills=f.loc[f.date.isin(dates)]
                costs.append({'strategy':strategy,'phase':phase,'lots':fills.quantity.abs().sum(),'fill_segments':len(fills),'commission':fills.commission.sum(),'base_slippage':fills.base_slippage_cost.sum(),'roll_slippage':fills.roll_slippage_cost.sum(),'impact':fills.impact_cost.sum(),'traded_notional':fills.traded_notional.sum(),'annualized_notional_turnover':fills.traded_notional.sum()/eq.loc[dates].equity.mean()/(len(dates)/252)})
                for dimension in ['year','sector','instrument','position_direction']:
                    group=g.groupby(dimension).net_pnl.sum();positive=group.clip(lower=0);total=positive.sum()
                    concentrations.append({'strategy':strategy,'phase':phase,'dimension':dimension,'top_positive_share':positive.max()/total if total else np.nan,'top_two_positive_share':positive.nlargest(2).sum()/total if total else np.nan,'positive_profit_hhi':((positive/total)**2).sum() if total else np.nan,'net_profit':group.sum()})
                    for member,amount in group.items():contributions.append({'strategy':strategy,'phase':phase,'dimension':dimension,'member':str(member),'net_pnl':amount})
                chem=g.loc[g.sector.eq('chemical_energy')].groupby('instrument').net_pnl.sum();fg=chem.get('FG',0.)
                concentrations.append({'strategy':strategy,'phase':phase,'dimension':'FG_dependence','net_profit':g.net_pnl.sum(),'fg_profit':fg,'chemical_profit':chem.sum(),'fg_share_chemical_positive_profit':max(fg,0)/chem.clip(lower=0).sum() if chem.clip(lower=0).sum() else np.nan,'fg_share_total_net_profit':fg/g.net_pnl.sum() if g.net_pnl.sum() else np.nan})
                factor=net.loc[mask,SLOW].std()/net.loc[mask,strategy].std()
                equal.append({'strategy':strategy,'phase':phase,'scale':factor,'interpretation':'事后固定风险归一化，非重跑',**metrics(net.loc[mask,strategy]*factor)})
        for year in range(2020,2027):
            for label,mask in [('train_5_years',(net.index.year>=year-5)&(net.index.year<year)),('next_year',net.index.year==year)]:
                walk.append({'strategy':strategy,'test_year':year,'slice':label,'selection':'固定策略、不按训练收益择优','partial_year':year==2026,**metrics(net.loc[mask,strategy])})
        walk.append({'strategy':strategy,'test_year':'stitched','slice':'next_year_stitched','selection':'2020起既有固定运行拼接','partial_year':True,**metrics(net.loc[net.index.year>=2020,strategy])})
    for name,rows in [('performance',records),('walk_forward',walk),('equal_realized_risk',equal),('contributions',contributions),('concentration',concentrations),('cost_turnover',costs)]:save(pd.DataFrame(rows),root,name+'_v4_2')
    reb,margin=_execution_stats(results);save(reb,root,'buffer_statistics_v4_2');save(margin,root,'margin_leverage_v4_2')


def sleeve_target_analysis(root,results,data):
    diagnostics=[];changes_all=[];risk_contributions=[];virtual_risk=[];virtual_daily=[];cost_quotes=[]
    from .costs_v3 import FeeSchedule
    fees=FeeSchedule.load(root.parent.parent/'data/v3/fees/historical_fee_rules')
    bars=data.bars.set_index(['date','ts_code'])
    for ident,strategy in [('S1',SLEEVE),('S2',STRESS)]:
        path=root/f'{ident}__{strategy}';internal=pd.read_pickle(path/'internal_targets.pkl');net=pd.read_pickle(path/'net_target_stages.pkl');r=results[strategy]
        budget=internal.groupby(['date','horizon','sector']).agg(allocated=('allocated_annual_risk','sum'),equity=('equity','first'),risk_fraction=('risk_fraction','sum'),unused=('unused_annual_risk','sum')).reset_index()
        budget['expected']=budget.equity*.275*.1;budget['error']=(budget.allocated-budget.expected).abs()
        if budget.error.max()>.01 or not np.allclose(budget.risk_fraction,.1):raise AssertionError('Sleeve budget transfer detected')
        save(budget,path,'fixed_budget_audit')
        dates=pd.DatetimeIndex(r.equity.date)
        # Dense contract grid preserves explicit exits to zero; missing targets are
        # zero by target-dictionary semantics, never missing-return imputation.
        legs={}
        for horizon,g in internal.dropna(subset=['contract']).groupby('horizon'):
            wide=g.pivot(index='date',columns='contract',values='internal_target').reindex(dates).fillna(0)
            legs[horizon]=wide
        contracts=sorted(set().union(*(frame.columns for frame in legs.values())))
        legs={h:frame.reindex(columns=contracts,fill_value=0) for h,frame in legs.items()}
        gross_change=sum(frame.diff().fillna(frame.iloc[0]).abs() for frame in legs.values())
        raw_net=sum(legs.values());net_change=raw_net.diff().fillna(raw_net.iloc[0]).abs()
        needed=data.bars.loc[data.bars.ts_code.isin(contracts)].copy()
        needed['mark']=needed.settlement.where(needed.settlement.gt(0)&needed.settlement.notna(),needed.close)
        mark=needed.pivot(index='date',columns='ts_code',values='mark').reindex(index=dates,columns=contracts)
        op=needed.pivot(index='date',columns='ts_code',values='open').reindex(index=dates,columns=contracts)
        pv=needed.groupby('ts_code').point_value.first().reindex(contracts)
        prev_equity=r.equity.set_index('date').equity-r.equity.set_index('date').net_pnl
        for horizon,target in legs.items():
            held=target.shift(1).fillna(0);prior=held.shift(1).fillna(0);delta=held-prior
            carry=(prior*(mark-mark.shift(1))).where(prior.ne(0),0)
            intraday=(delta*(mark-op)).where(delta.ne(0),0)
            pnl=(carry+intraday).mul(pv,axis=1)
            if pnl.isna().any().any():raise ValueError('Missing price for a nonzero virtual exposure; cannot silently fill')
            daily=pnl.sum(axis=1);ret=daily/prev_equity
            virtual_daily.append(pd.DataFrame({'date':dates,'strategy':strategy,'horizon':horizon,'virtual_gross_pnl':daily.values,'virtual_return_on_real_equity':ret.values,'diagnostic_only':True}))
            for phase,mask in phase_slices(dates).items():virtual_risk.append({'strategy':strategy,'horizon':horizon,'phase':phase,'virtual_gross_realized_vol':ret.loc[mask].std()*np.sqrt(252),'diagnostic':'内部原始目标次日开盘无成本盯市；未过容量/buffer/约束，不是实际袖套收益'})
        cancelled=(gross_change-net_change).clip(lower=0)
        sparse=cancelled.stack();sparse=sparse[sparse>0]
        next_dates=dict(zip(dates[:-1],dates[1:]))
        meta=data.contract_meta.set_index('ts_code')
        for (created,contract),lots in sparse.items():
            execution=next_dates.get(created)
            if execution is None:continue
            bar=bars.loc[(execution,contract)] if (execution,contract) in bars.index else None
            if bar is None or not np.isfinite(bar.open):
                cost_quotes.append({'strategy':strategy,'date':created,'contract':contract,'cancelled_target_change_lots':lots,'quoted':False});continue
            instrument=str(bar.instrument);base=3 if strategy==STRESS else (1 if instrument in ['T','RB','AL'] else 2)
            tick=float(bar.tick_size);point=float(bar.point_value)
            quote=fees.charge(contract,instrument,execution,'open',1,float(bar.open),point,1.5)
            cost_quotes.append({'strategy':strategy,'date':created,'hypothetical_execution_date':execution,'contract':contract,
                                'cancelled_target_change_lots':lots,'quoted':True,'normal_base_tick_proxy':base,
                                'base_slippage_avoidance_proxy':lots*base*tick*point,'open_fee_avoidance_proxy':lots*quote.client_fee,
                                'historical_fee_rule':quote.rule_id,'fee_rule_is_proxy':quote.is_proxy,
                                'note':'仅原始目标抵消的线性报价，不含buffer/约束/部分成交/冲击/换月/平仓类型，非实际现金节省'})
        changes=pd.DataFrame({'date':dates,'internal_target_change_lots':gross_change.sum(axis=1).values,'raw_net_target_change_lots':net_change.sum(axis=1).values})
        changes['potential_cancelled_target_change_lots']=changes.internal_target_change_lots-changes.raw_net_target_change_lots
        changes['strategy']=strategy;changes_all.append(changes)
        diagnostics.append({'strategy':strategy,'gross_internal_daily_target_lots':internal.internal_target.abs().sum(),'raw_net_daily_target_lots':net.raw_net_target.abs().sum(),'cancelled_internal_target_lots':net.cancelled_internal_lots.sum(),'internal_target_change_lots':changes.internal_target_change_lots.sum(),'raw_net_target_change_lots':changes.raw_net_target_change_lots.sum(),'potential_cancelled_target_change_lots':changes.potential_cancelled_target_change_lots.sum(),'actual_fill_lots':r.fills.quantity.abs().sum(),'actual_cost':r.fills.commission.sum()+r.fills.slippage_cost.sum(),'actual_cash_saving_vs_unnetted_account':np.nan,'cash_saving_status':'未运行独立非净额账户；不能把虚拟目标抵消量当作已实现现金节省'})
        prev=r.equity.set_index('date').equity-r.equity.set_index('date').net_pnl
        sector=r.pnl_by_instrument.groupby(['date','sector']).net_pnl.sum().unstack().reindex(dates).fillna(0).divide(prev,axis=0)
        total=returns_from_result(r)
        for phase,mask in phase_slices(dates).items():
            for name in sector:
                cov=sector.loc[mask,name].cov(total.loc[mask]);variance=total.loc[mask].var()
                risk_contributions.append({'strategy':strategy,'phase':phase,'sector':name,'realized_annual_standalone_vol':sector.loc[mask,name].std()*np.sqrt(252),'portfolio_variance_contribution_fraction':cov/variance,'annual_covariance_contribution':cov*252})
    save(pd.DataFrame(diagnostics),root,'netting_summary_v4_2');save(pd.concat(changes_all,ignore_index=True),root,'target_change_netting_v4_2');save(pd.DataFrame(risk_contributions),root,'sector_realized_risk_contributions_v4_2')
    save(pd.DataFrame(virtual_risk),root,'internal_virtual_realized_risk_v4_2');save(pd.concat(virtual_daily,ignore_index=True),root,'internal_virtual_daily_risk_pnl_v4_2');save(pd.DataFrame(cost_quotes),root,'cancelled_target_cost_proxy_v4_2')


def analyze_v42(settings,root,results,data):
    net=pd.concat({k:returns_from_result(r) for k,r in results.items()},axis=1)
    pre=pd.concat({k:returns_from_result(r,True) for k,r in results.items()},axis=1)
    if net.isna().any().any() or pre.isna().any().any() or net.index.has_duplicates:raise AssertionError('Missing/misaligned return date; cannot fill zero')
    save(net.rename_axis('date').reset_index(),root,'daily_net_returns_v4_2');save(pre.rename_axis('date').reset_index(),root,'daily_pre_cost_diagnostic_returns_v4_2')
    daily=[]
    for strategy,r in results.items():
        e=r.equity.copy();components=slippage_components(r.fills).groupby('date')[['base_slippage_cost','roll_slippage_cost','impact_cost']].sum()
        e=e.merge(components,on='date',how='left');cols=['base_slippage_cost','roll_slippage_cost','impact_cost'];e[cols]=e[cols].fillna(0)
        e['same_path_pre_cost_pnl']=e.net_pnl+e.fees+e[cols].sum(axis=1)
        e['frozen_lots_pre_cost_equity']=float(settings.section('run')['initial_capital'])+e.same_path_pre_cost_pnl.cumsum()
        e['strategy']=strategy;daily.append(e)
    save(pd.concat(daily,ignore_index=True),root,'daily_account_and_cost_paths_v4_2')
    performance_tables(net,pre,results,root);print('Performance, costs and attribution saved',flush=True)
    from .analytics_v4_1 import cost_event_attribution
    save(pd.concat([cost_event_attribution(label,r,data.instrument_meta) for label,r in results.items()],ignore_index=True),root,'execution_cost_attribution_v4_2')
    sleeve_target_analysis(root,results,data)
    correlation_analysis(net,pre,root);print('Drawdown, conditional and rolling statistics saved',flush=True)
    bootstrap_analysis(net,pre,root)
    from .reports_v4_2 import reports_v42
    reports_v42(settings,root)
