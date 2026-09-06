"""Independent read-only legacy audit. Never launches a historical engine scenario."""
from datetime import datetime, timezone
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest

sys.dont_write_bytecode = True
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
sys.path.insert(0, str(ROOT / 'tests'))
import pandas as pd
from five_sector_momentum.settings import Settings


def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def both(frame, out, name):
    frame.to_csv(out / f'{name}.csv', index=False, encoding='utf-8-sig')
    frame.to_pickle(out / f'{name}.pkl')


class DetailResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.rows = []

    def addSuccess(self, test):
        super().addSuccess(test)
        self.rows.append({'test': test.id(), 'status': 'PASS', 'detail': ''})

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.rows.append({'test': test.id(), 'status': 'FAIL', 'detail': self._exc_info_to_string(err, test)})

    def addError(self, test, err):
        super().addError(test, err)
        self.rows.append({'test': test.id(), 'status': 'ERROR', 'detail': self._exc_info_to_string(err, test)})

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.rows.append({'test': test.id(), 'status': 'SKIP', 'detail': reason})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--diagnostic-recheck', action='store_true', help='Retain first logs; recheck only new tests after aligning eligibility column schemas')
    args = parser.parse_args()
    settings = Settings.load(ROOT / 'configs/five_sector_momentum_v4_2.yaml')
    out = ROOT / settings.section('v4_2_research')['output_directory']
    if args.diagnostic_recheck:
        out = out / 'preflight_recheck_02'
    out.mkdir(parents=True, exist_ok=False)
    registry = ROOT / 'docs/V4_2_EXPERIMENT_REGISTRY.md'
    (out / 'EXPERIMENT_REGISTRY_20SKIP5_250_SLEEVE.md').write_bytes(registry.read_bytes())
    protected = set((ROOT / 'src/five_sector_momentum').glob('*.py'))
    protected.update(p for p in (ROOT / 'configs').glob('*.yaml') if p.name != 'five_sector_momentum_v4_2.yaml')
    protected.update(p for p in (ROOT / 'tests').glob('test*.py') if p.name != 'test_v4_2_preflight.py')
    protected.update((ROOT / 'data/normalized_v2').glob('*'))
    protected.add(registry)
    for relative in ['02_single_skip__single_20_skip5', '01_single_normal__single_250']:
        protected.update((ROOT / 'outputs/v4_20260902_102628' / relative).glob('*'))
    before = {p: digest(p) for p in sorted(protected) if p.is_file()}
    loader = unittest.TestLoader()
    rows = []
    passed = True
    suites = [
        ('legacy_tests', loader.loadTestsFromNames(['test_core', 'test_v3', 'test_v4', 'test_v4_1'])),
        ('v4_2_preflight_tests', loader.loadTestsFromName('test_v4_2_preflight')),
    ]
    if args.diagnostic_recheck:
        suites = suites[1:]
    for name, suite in suites:
        print(f'START {name}', flush=True)
        with (out / f'{name}.txt').open('w', encoding='utf-8') as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2, failfast=True, resultclass=DetailResult).run(suite)
        rows.extend(result.rows)
        print(f'END {name}: tests={result.testsRun}, failures={len(result.failures)}, errors={len(result.errors)}', flush=True)
        if not result.wasSuccessful():
            passed = False
            break
    if 'test_v4_2_preflight' in sys.modules:
        test_class = sys.modules['test_v4_2_preflight'].V42PreflightTests
        for name, frame in test_class.evidence.items():
            both(frame, out, name)
    both(pd.DataFrame(rows), out, 'all_test_results_v4_2')
    manifest = pd.DataFrame([{'path': str(p.relative_to(ROOT)), 'sha256_before': value, 'sha256_after': digest(p)} for p, value in before.items()])
    manifest['unchanged'] = manifest.sha256_before.eq(manifest.sha256_after)
    both(manifest, out, 'protected_input_manifest_v4_2')
    if not manifest.unchanged.all():
        passed = False
    statuses = pd.DataFrame([
        {'order': i, 'id': ident, 'scenario': label, 'status': 'NOT_RUN', 'historical_engine_runs': 0}
        for i, (ident, label) in enumerate([
            ('G1', 'single_20_skip5'), ('G2', 'single_250'),
            ('S1', 'strategy_sleeve_20skip5_250_equal_risk'),
            ('S2', 'strategy_sleeve_20skip5_250_equal_risk_fixed_3tick'),
        ], 1)
    ])
    both(statuses, out, 'scenario_status_v4_2')
    status = {
        'status': 'PREFLIGHT_PASSED_NOT_YET_REPRODUCED' if passed else 'STOPPED_PREFLIGHT_FAILURE',
        'historical_engine_runs': 0, 'maximum_historical_engine_runs': 4,
        'registry_sha256': before[registry], 'protected_files_unchanged': bool(manifest.unchanged.all()),
        'tests_run': len(rows), 'test_status_counts': pd.DataFrame(rows).status.value_counts().to_dict(),
        'finished_utc': datetime.now(timezone.utc).isoformat(),
        'no_accounting_or_reproduction_gate_claim': True,
    }
    (out / 'execution_status_v4_2.json').write_text(json.dumps(status, indent=2, ensure_ascii=False), encoding='utf-8')
    print(json.dumps(status, ensure_ascii=False), flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
