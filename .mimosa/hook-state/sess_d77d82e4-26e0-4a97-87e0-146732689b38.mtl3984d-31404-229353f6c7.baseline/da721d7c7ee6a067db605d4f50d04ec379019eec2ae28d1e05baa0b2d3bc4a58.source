"""Package existing v4.2 stopping evidence only; no research or engine runs."""
import hashlib
import json
from pathlib import Path
import re
import sys

sys.dont_write_bytecode = True
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'outputs/v4_2_20260903_072724'
RECHECK = OUT / 'preflight_recheck_02'


def both(frame, name):
    for suffix in ['csv', 'pkl']:
        if (OUT / f'{name}.{suffix}').exists():
            raise FileExistsError(OUT / f'{name}.{suffix}')
    frame.to_csv(OUT / f'{name}.csv', index=False, encoding='utf-8-sig')
    frame.to_pickle(OUT / f'{name}.pkl')


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def main():
    # This is packaging of completed checks, not another diagnostic or experiment.
    initial = pd.read_pickle(OUT / 'all_test_results_v4_2.pkl')
    initial['attempt'] = initial.test.map(lambda value: 'initial_preflight' if value.startswith('test_v4_2_preflight.') else 'legacy')
    second = pd.read_pickle(RECHECK / 'all_test_results_v4_2.pkl')
    second['attempt'] = 'preflight_recheck_02'
    records = pd.concat([initial, second], ignore_index=True)
    both(records, 'all_test_attempts_v4_2')
    summary = records.groupby('attempt', sort=False).status.agg(
        tests='size', passed=lambda values: int(values.eq('PASS').sum()),
        failed=lambda values: int(values.eq('FAIL').sum()),
        errors=lambda values: int(values.eq('ERROR').sum()),
    ).reset_index()
    both(summary, 'test_attempt_summary_v4_2')
    mismatch = pd.read_pickle(RECHECK / 'weekly_prefix_mismatches.pkl')
    case_summary = mismatch.groupby('case', sort=False).agg(
        changed_history_rows=('case', 'size'),
        actual_direction_changes=('direction_equal', lambda values: int((~values).sum())),
    ).reset_index()
    both(case_summary, 'weekly_case_summary_v4_2')
    assert len(mismatch) == 35 and int((~mismatch.direction_equal).sum()) == 3
    assert len(records) == 50 and records.status.eq('PASS').sum() == 48
    final_tests = records.drop_duplicates('test', keep='last')
    assert len(final_tests) == 49 and final_tests.status.eq('FAIL').sum() == 1
    both(final_tests, 'effective_test_results_v4_2')

    with (ROOT / 'configs/five_sector_momentum_v4_1.yaml').open(encoding='utf-8') as stream:
        old = yaml.safe_load(stream)
    with (ROOT / 'configs/five_sector_momentum_v4_2.yaml').open(encoding='utf-8') as stream:
        new = yaml.safe_load(stream)
    inherited = [key for key in old if key not in ['version', 'v4_1_research']]
    config_check = pd.DataFrame([{'section': key, 'unchanged': old[key] == new[key]} for key in inherited])
    assert config_check.unchanged.all()
    both(config_check, 'inherited_config_verification_v4_2')

    protected = pd.read_pickle(RECHECK / 'protected_input_manifest_v4_2.pkl')
    protected['sha256_at_finalization'] = protected.path.map(lambda name: digest(ROOT / name))
    protected['still_unchanged'] = protected.sha256_before.eq(protected.sha256_at_finalization)
    assert protected.still_unchanged.all()
    both(protected, 'final_protected_input_verification_v4_2')

    final_status = {
        'status': 'STOPPED_CONFIRMED_WEEKLY_PREFIX_INVARIANCE_FAILURE',
        'completed_research': False, 'historical_engine_runs': 0, 'registered_engine_run_limit': 4,
        'G1': 'NOT_RUN', 'G2': 'NOT_RUN', 'S1': 'NOT_RUN', 'S2': 'NOT_RUN',
        'bootstrap': 'NOT_RUN', 'new_historical_accounting_reconciliation': 'NOT_RUN',
        'legacy_tests_passed': 47, 'final_new_tests_passed': 1, 'final_new_tests_failed': 1,
        'first_test_schema_mismatch_preserved_and_resolved': True,
        'raw_test_executions': 50, 'raw_passes': 48, 'raw_failures': 2,
        'real_data_changed_signal_date_rows': 34, 'real_data_changed_direction_rows': 2,
        'hand_example_changed_direction_rows': 1, 'protected_files_verified_unchanged': len(protected),
        'prior_results_profit_impact': 'NOT_QUANTIFIED',
        'registry_sha256': digest(ROOT / 'docs/V4_2_EXPERIMENT_REGISTRY.md'),
        'next_action_requires_separate_authorization': 'Independent calendar fix and reproduction-baseline impact audit',
    }
    path = OUT / 'FINAL_STATUS_v4_2.json'
    if path.exists():
        raise FileExistsError(path)
    path.write_text(json.dumps(final_status, indent=2, ensure_ascii=False), encoding='utf-8')

    added_sources = [
        'docs/V4_2_EXPERIMENT_REGISTRY.md', 'configs/five_sector_momentum_v4_2.yaml',
        'tests/test_v4_2_preflight.py', 'scripts/audit_v4_2_preflight.py',
        'scripts/finalize_v4_2_stop_report.py',
    ]
    paths = [ROOT / name for name in added_sources] + sorted(p for p in OUT.rglob('*') if p.is_file())
    paths += [OUT / 'file_inventory_v4_2.csv', OUT / 'file_inventory_v4_2.pkl']
    both(pd.DataFrame([{'path': str(p.relative_to(ROOT)), 'operation': '新增，仅v4.2'} for p in paths]), 'file_inventory_v4_2')

    # Only artifact-level checks below; no continuation of stopped research.
    for csv in OUT.rglob('*.csv'):
        pickle = csv.with_suffix('.pkl')
        assert pickle.exists(), f'Missing pickle: {pickle}'
        a, b = pd.read_csv(csv), pd.read_pickle(pickle)
        assert list(a.columns) == list(b.columns) and len(a) == len(b), csv
    for document in [OUT / 'BACKTEST_ENGINE_AUDIT_v4_2.md', OUT / 'BACKTEST_RESULT_REPORT_v4_2.md', OUT / 'DRAWDOWN_CORRELATION_REPORT_v4_2.md']:
        for target in re.findall(r'\]\(([^)]+)\)', document.read_text(encoding='utf-8')):
            assert (document.parent / target).exists(), f'Broken local link: {target}'
    print(json.dumps(final_status, ensure_ascii=False, indent=2))
    print('Artifact checks: CSV/pickle pairs, report links, config inheritance, protected-input hashes passed.')


if __name__ == '__main__':
    main()
