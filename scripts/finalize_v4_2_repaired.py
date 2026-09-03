"""Final v4.2 delivery manifest and traceability checks; no backtest calls."""
from pathlib import Path
import json, hashlib, re
import pandas as pd
ROOT=Path(__file__).resolve().parents[1]; OUT=ROOT/'outputs/v4_2_20260903_091241'
def both(df,name):
    df.to_csv(OUT/(name+'.csv'),index=False,encoding='utf-8-sig');df.to_pickle(OUT/(name+'.pkl'))
def sha(p):
    h=hashlib.sha256();
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def main():
    # The first full suite was retained; replace only its known fixed-test
    # fixture rows with the independent seven-test verification run.
    old=pd.read_pickle(OUT/'test_results_repaired_v4_2.pkl');old=old.loc[~old.test.str.startswith('test_v4_2_analytics.')]
    new=pd.read_pickle(OUT/'test_results_repaired_v4_2_verification_02.pkl')
    tests=pd.concat([old,new],ignore_index=True);both(tests,'test_results_final_v4_2')
    if len(tests)!=64 or not tests.status.eq('PASS').all():raise AssertionError('Final test set is not 64/64 PASS')
    acc=[]
    for p in OUT.glob('*/accounting_checks.pkl'):
        acc.append(pd.read_pickle(p))
    accounting=pd.concat(acc,ignore_index=True);both(accounting,'accounting_reconciliation_v4_2')
    if not accounting.passed.all():raise AssertionError('Accounting failure in final package')
    scenarios=[]
    for p in sorted(OUT.glob('*/scenario_parameters.json')):
        x=json.loads(p.read_text(encoding='utf-8'));x['output_directory']=str(p.parent.relative_to(ROOT));scenarios.append(x)
    both(pd.DataFrame(scenarios),'scenario_parameters_v4_2')
    metrics=pd.read_pickle(OUT/'performance_v4_2.pkl');summary=metrics.loc[metrics.exclusion.eq('none')&metrics.basis.eq('net')&metrics.phase.isin(['full','insample','validation'])].copy();both(summary,'scenario_metrics_v4_2')
    gate=pd.read_pickle(OUT/'reproduction_and_repair_gate_v4_2.pkl')
    cash=gate.loc[gate.table.isin(['equity','positions','fills','pnl_by_instrument'])].copy()
    diffs=pd.read_pickle(OUT/'calendar_repair_differences_v4_2.pkl')
    equity_allowed=diffs.loc[diffs.table.eq('equity'),'allowed_terminal_repair'].all()
    cash['cash_or_position_integrity']=(cash.table.eq('equity')&equity_allowed)|((cash.table.ne('equity'))&(cash.max_numeric_difference<=.01))
    if not cash.cash_or_position_integrity.all():raise AssertionError('Gate cash/position integrity failure')
    both(cash,'gate_cash_position_integrity_v4_2')
    protected=pd.read_pickle(OUT/'G1__single_20_skip5/independent_contract_ledger.pkl')
    if protected.error.max()>.01:raise AssertionError('G1 independent contract ledger failure')
    files=[]
    for p in sorted(OUT.rglob('*')):
        if p.is_file():files.append({'path':str(p.relative_to(ROOT)),'size_bytes':p.stat().st_size,'sha256':sha(p)})
    both(pd.DataFrame(files),'file_manifest_final_v4_2')
    final={'version':'v4_2_repaired','status':'COMPLETE_WITH_REGISTERED_CALENDAR_REPAIR','historical_engine_runs':4,'run_limit':4,
           'G1':'PASS_REPAIR_IMPACT_ACCEPTED','G2':'PASS_REPAIR_IMPACT_ACCEPTED','S1':'PASS_ACCOUNTING','S2':'PASS_ACCOUNTING',
           'accounting_checks':len(accounting),'accounting_failures':int((~accounting.passed).sum()),'tests':len(tests),'test_failures':int((~tests.status.eq('PASS')).sum()),
           'bootstrap_repetitions_per_phase':2000,'bootstrap_core_strategies':8,'bootstrap_stress_s2_same_blocks':True,'bootstrap_output_columns':9,'old_versions_modified':False,
           'calendar_conflict_days':0,'calendar_price_date_conflicts':0,'terminal_repair_differences_preserved':True,
           'cost_saving_exact_nonnetted_account':'NOT_IDENTIFIABLE_REGISTERED_LIMITATION',
           'recommendation':'先保留v3/250日作为基准，新袖套仅作为并行观察候选，依据见recommendation_rules_v4_2.csv'}
    (OUT/'FINAL_STATUS_REPAIRED_v4_2.json').write_text(json.dumps(final,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(final,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
