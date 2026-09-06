"""Registered four-run workflow with immutable results and hard audit gates."""
from pathlib import Path
import hashlib
import json
import os
import subprocess
import sys
import numpy as np
import pandas as pd
from .calendar_v4_2 import TradingCalendarV42
from .settings import Settings
from .data_pipeline import load_bundle
from .costs_v3 import FeeSchedule
from .signals_v4 import build_forecast_library_v4
from .signals_v4_2 import signal_bundle_v42
from .engine_v4_2 import BacktestEngineV42, SleeveEngineV42
from .engine_v4_1 import ScenarioV41, COST_SPECS, combined_sleeve_signal
from .workflow_v4_1 import _load_result, _save_result, _both, V4_DIRS


def save(frame, root, name):
    _both(frame,root/name)


def accounting_v42(label,r,initial):
    e=r.equity.set_index('date');f=r.fills;p=r.pnl_by_instrument
    checks={'equity_daily':(e.equity-e.equity.shift().fillna(initial)-e.net_pnl).abs().max(),
            'equity_terminal':abs(e.net_pnl.sum()-(e.equity.iloc[-1]-initial)),
            'net_equals_gross_less_fees':(e.net_pnl-e.gross_pnl+e.fees).abs().max(),
            'daily_pnl_contracts':(p.groupby('date').net_pnl.sum().reindex(e.index,fill_value=0)-e.net_pnl).abs().max(),
            'daily_commission':(f.groupby('date').commission.sum().reindex(e.index,fill_value=0)-e.fees).abs().max(),
            'daily_contract_commission':(p.groupby('date').commission.sum().reindex(e.index,fill_value=0)-e.fees).abs().max()}
    from .analytics_v4_1 import slippage_components
    comp=slippage_components(f)
    checks['slippage_components']=(comp.base_slippage_cost+comp.roll_slippage_cost+comp.impact_cost-comp.slippage_cost).abs().max()
    checks['next_day_execution']=float((f.date<=f.created_date).sum())
    # Independent settlement ledger recomputation uses prior positions and fills.
    rows=[{'strategy':label,'check':k,'error':float(v),'tolerance':.01,'passed':bool(v<=.01)} for k,v in checks.items()]
    return pd.DataFrame(rows)


def compare_gate(label,signals,r,old_path,terminal,calendar):
    old=_load_result(old_path)
    pairs=[('scores',signals.scores,pd.read_pickle(old_path/'scores.pkl'),['date','instrument'],'date'),
           ('selections',signals.selections,pd.read_pickle(old_path/'selections.pkl'),['signal_date','sector','instrument','role'],'signal_date'),
           ('directions',signals.directions,pd.read_pickle(old_path/'directions.pkl'),['date','instrument'],'date')]
    for attr,keys,dc in [('equity',['date'],'date'),('targets',['date','contract'],'date'),('positions',['date','contract'],'date'),('orders',['created_date','contract','quantity'],'created_date'),('fills',['date','created_date','contract','segment_index'],'date'),('pnl_by_instrument',['date','contract'],'date')]:
        pairs.append((attr,getattr(r,attr),getattr(old,attr),keys,dc))
    summaries=[]; differences=[]
    terminal_is_incomplete=terminal not in calendar.weekly_signal_dates(pd.DatetimeIndex([terminal]))
    allowed_tables={'selections','directions','targets','orders'}
    for name,new,prior,keys,dc in pairs:
        columns=[col for col in new if col!='scenario']
        if set(columns)!=set(prior.columns)-{'scenario'}:raise AssertionError(f'Gate schema differs: {name}')
        keys=[key for key in keys if key in columns]
        joined=new[columns].merge(prior[columns],on=keys,suffixes=('_new','_old'),how='outer',indicator=True,validate='one_to_one')
        mismatched=np.zeros(len(joined),dtype=bool); maxdiff=0.
        for col in columns:
            if col in keys:continue
            a,b=joined[col+'_new'],joined[col+'_old']
            if pd.api.types.is_numeric_dtype(new[col]) and not pd.api.types.is_bool_dtype(new[col]):
                delta=(a-b).abs()
                tol=0. if pd.api.types.is_integer_dtype(new[col]) else (1e-12 if name=='scores' else .01)
                eq=delta.le(tol)|(a.isna()&b.isna())
                if delta.notna().any():maxdiff=max(maxdiff,float(delta.max()))
            else:eq=a.eq(b)|(a.isna()&b.isna())
            mismatch=~eq|joined['_merge'].ne('both');mismatched|=mismatch.to_numpy()
            for idx in joined.index[mismatch]:
                row=joined.loc[idx]
                day=row[dc] if dc in keys else row.get(dc+'_new',row.get(dc+'_old'))
                # These three columns live in the equity FILE but describe the
                # pending target, not the realized account. Preserve cash checks.
                target_diagnostic = name=='equity' and col in {'pending_orders','exante_vol_before_scaling','diversification_multiplier'}
                allowed=bool(terminal_is_incomplete and (name in allowed_tables or target_diagnostic) and day==terminal)
                differences.append({'strategy':label,'table':name,'date':day,'key':'|'.join(str(row[k]) for k in keys),
                                    'field':col,'new_value':str(a.loc[idx]),'old_value':str(b.loc[idx]),'allowed_terminal_repair':allowed})
        # Row-only differences are already represented by compared fields above.
        relevant=[x for x in differences if x['strategy']==label and x['table']==name]
        summaries.append({'strategy':label,'table':name,'new_rows':len(new),'old_rows':len(prior),'max_numeric_difference':maxdiff,
                          'strict_reproduction':not bool(mismatched.any()),
                          'repair_impact_accepted':all(x['allowed_terminal_repair'] for x in relevant),
                          'changed_rows':int(mismatched.sum())})
    if ((old.fills.created_date==terminal)|(r.fills.created_date==terminal)).any():
        raise AssertionError('Terminal pending order unexpectedly filled in sample')
    return pd.DataFrame(summaries),pd.DataFrame(differences)


def audit_independent_ledger(label,r,data,initial):
    # Does not call engine accounting functions; explicit day x contract identity.
    bars=data.bars.set_index(['date','ts_code']);prev={};last_marks={};rows=[]
    fill_groups={day:group for day,group in r.fills.groupby('date')}
    pos_groups={day:dict(zip(group.contract,group.quantity)) for day,group in r.positions.groupby('date')} if 'quantity' in r.positions else {}
    if not pos_groups:
        quantity='position' if 'position' in r.positions else 'contracts'
        pos_groups={day:dict(zip(group.contract,group[quantity])) for day,group in r.positions.groupby('date')}
    details=r.pnl_by_instrument.set_index(['date','contract'])
    for e in r.equity.itertuples():
        day=e.date;fills=fill_groups.get(day,pd.DataFrame());contracts=set(prev)|(set(fills.contract) if not fills.empty else set());gross=0.;fees=0.
        for contract in sorted(contracts):
            bar=bars.loc[(day,contract)];mark=float(bar.settlement if np.isfinite(bar.settlement) and bar.settlement>0 else bar.close)
            pv=float(bar.point_value);sub=fills.loc[fills.contract.eq(contract)] if not fills.empty else fills
            pnl=prev.get(contract,0)*(mark-last_marks.get(contract,mark))*pv
            cost=0.
            if not sub.empty:
                pnl+=float((sub.quantity*(mark-sub.price)*pv).sum());cost=float(sub.commission.sum())
            gross+=pnl;fees+=cost
            actual=details.loc[(day,contract)].net_pnl if (day,contract) in details.index else 0.
            rows.append({'strategy':label,'date':day,'contract':contract,'expected_net_pnl':pnl-cost,'recorded_net_pnl':actual,'error':abs(pnl-cost-actual)})
        prev=pos_groups.get(day,{})
        for contract in prev:
            bar=bars.loc[(day,contract)];last_marks[contract]=float(bar.settlement if np.isfinite(bar.settlement) and bar.settlement>0 else bar.close)
        if abs(gross-fees-e.net_pnl)>.01:raise AssertionError(f'Independent ledger failed {label} {day}')
    frame=pd.DataFrame(rows)
    if not frame.empty and frame.error.max()>.01:raise AssertionError('Contract ledger mismatch')
    return frame


def run_v42(settings, phase='gates'):
    project=settings.path.parent.parent;root=project/settings.section('v4_2_research')['output_directory'];root.mkdir(exist_ok=True,parents=True)
    for name in ['V4_2_EXPERIMENT_REGISTRY.md','V4_2_CALENDAR_REPAIR_ADDENDUM.md']:
        target=root/name
        if not target.exists():target.write_bytes((project/'docs'/name).read_bytes())
    if not (root/settings.path.name).exists():(root/settings.path.name).write_bytes(settings.path.read_bytes())
    calendar=TradingCalendarV42.load(project/settings.section('v4_2_research')['calendar_path'])
    data=load_bundle(settings);lib=build_forecast_library_v4(settings,data)
    save(calendar.daily,root,'independent_calendar_consensus_v4_2')
    calendar_check=calendar.audit_observed_dates(lib.prices.index);save(calendar_check,root,'calendar_price_date_audit_v4_2')
    if calendar_check['count'].sum():raise AssertionError('Calendar/price data conflict')
    signals={label:signal_bundle_v42(settings,data,lib,forecast,label,calendar) for label,forecast in [('single_20_skip5',lib.raw_skip5[20]),('single_250',lib.raw_regular[250])]}
    fees=FeeSchedule.load(project/settings.section('fees')['rules_path']);source=project/settings.section('v4_2_research')['source_v4_output']
    gate_rows=[];gate_diffs=[];accounts=[];results={};terminal=lib.prices.index[-1]
    ledger_path=root/'engine_run_ledger_v4_2.json'
    ledger=json.loads(ledger_path.read_text()) if ledger_path.exists() else []
    def execute(ident,label,engine,bundle,cost):
        path=root/f'{ident}__{label}'
        if path.is_dir():
            if not (path/'complete.json').exists():raise RuntimeError('Incomplete historical run retained; do not silently rerun')
            return _load_result(path)
        if len(ledger)>=4:raise RuntimeError('Four-run cap reached')
        ledger.append({'id':ident,'label':label,'status':'started'});ledger_path.write_text(json.dumps(ledger,indent=2),encoding='utf-8')
        print(f'START {ident} {label}',flush=True)
        r=engine.run_v4_2(ScenarioV41(label,ident,COST_SPECS[cost]))
        _save_result(path,r,bundle,pd.DataFrame(engine.internal_target_rows) if isinstance(engine,SleeveEngineV42) else None)
        if isinstance(engine,SleeveEngineV42):
            save(pd.DataFrame(engine.net_target_rows),path,'net_target_stages');save(pd.DataFrame(engine.risk_rows),path,'risk_stages')
        account=accounting_v42(label,r,float(settings.section('run')['initial_capital']));save(account,path,'accounting_checks')
        if not account.passed.all():raise AssertionError('Account reconciliation failed')
        independent=audit_independent_ledger(label,r,data,float(settings.section('run')['initial_capital']));save(independent,path,'independent_contract_ledger')
        (path/'complete.json').write_text(json.dumps({'complete':True,'accounting_passed':True}),encoding='utf-8')
        ledger[-1]['status']='completed';ledger_path.write_text(json.dumps(ledger,indent=2),encoding='utf-8')
        print(f'END {ident}: ending_equity={r.equity.equity.iloc[-1]:.2f}',flush=True)
        return r
    for ident,label in [('G1','single_20_skip5'),('G2','single_250')]:
        r=execute(ident,label,BacktestEngineV42(settings,data,signals[label],fees,calendar),signals[label],'C3')
        results[label]=r
        checks,diffs=compare_gate(label,signals[label],r,source/V4_DIRS[label],terminal,calendar)
        gate_rows.append(checks);gate_diffs.append(diffs)
        save(pd.concat(gate_rows,ignore_index=True),root,'reproduction_and_repair_gate_v4_2');save(pd.concat(gate_diffs,ignore_index=True),root,'calendar_repair_differences_v4_2')
        if not checks.repair_impact_accepted.all():raise AssertionError('Repair impact exceeds registered terminal-only exception; STOP')
    if phase=='gates':return root
    for ident,label,cost in [('S1','strategy_sleeve_20skip5_250_equal_risk','C3'),('S2','strategy_sleeve_20skip5_250_equal_risk_fixed_3tick','C7')]:
        engine=SleeveEngineV42(settings,data,signals,fees,calendar)
        results[label]=execute(ident,label,engine,combined_sleeve_signal(signals),cost)
    for label in ['single_20','single_60','single_120','single_180','reference_v3_252']:
        results[label]=_load_result(source/V4_DIRS[label])
    if phase=='runs':return root
    from .analytics_v4_2 import analyze_v42
    analyze_v42(settings,root,results,data)
    return root
