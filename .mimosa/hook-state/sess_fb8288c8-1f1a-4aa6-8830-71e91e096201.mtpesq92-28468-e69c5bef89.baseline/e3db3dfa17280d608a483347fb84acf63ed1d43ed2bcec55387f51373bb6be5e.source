import argparse
import os
from pathlib import Path
import sys
sys.dont_write_bytecode=True
os.environ['PYTHONDONTWRITEBYTECODE']='1'
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from five_sector_momentum.settings import Settings
from five_sector_momentum.workflow_v4_2 import run_v42
parser=argparse.ArgumentParser();parser.add_argument('--phase',choices=['gates','runs','analysis'],default='gates');args=parser.parse_args()
print(run_v42(Settings.load(ROOT/'configs/five_sector_momentum_v4_2_repaired.yaml'),args.phase))
