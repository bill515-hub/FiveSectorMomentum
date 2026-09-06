"""Explicit repaired suite; frozen defect-witness tests are not silently changed."""
import os
from pathlib import Path
import sys
import unittest
import argparse
sys.dont_write_bytecode=True
os.environ['PYTHONDONTWRITEBYTECODE']='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'tests')]
import pandas as pd
from audit_v4_2_preflight import DetailResult
out=ROOT/'outputs/v4_2_20260903_091241'
parser=argparse.ArgumentParser();parser.add_argument('--analytics-only',action='store_true');parser.add_argument('--suffix',default='');args=parser.parse_args()
stem='test_results_repaired_v4_2'+args.suffix
target=out/(stem+'.txt')
if target.exists():raise FileExistsError('Preserve previous test logs; use a new report path for another attempt')
names=['test_v4_2_analytics'] if args.analytics_only else ['test_core','test_v3','test_v4','test_v4_1','test_v4_2_repaired','test_v4_2_analytics']
suite=unittest.TestLoader().loadTestsFromNames(names)
with target.open('w',encoding='utf-8') as stream:
    result=unittest.TextTestRunner(stream=stream,verbosity=2,resultclass=DetailResult).run(suite)
df=pd.DataFrame(result.rows);df.to_csv(out/(stem+'.csv'),index=False,encoding='utf-8-sig');df.to_pickle(out/(stem+'.pkl'))
print(f'tests={result.testsRun} failures={len(result.failures)} errors={len(result.errors)}')
raise SystemExit(0 if result.wasSuccessful() else 1)
