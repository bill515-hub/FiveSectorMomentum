import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(r"D:\FiveSectorMomentum")
DATA = ROOT / "data" / "normalized_v2"

for n in ["mapping", "instrument_meta", "contract_meta"]:
    df = pd.read_pickle(DATA / f"{n}.pkl")
    print("="*60)
    print(n, df.shape, list(df.columns))
    print(df.head(3).to_string())
    print(df.tail(2).to_string())

fr = pd.read_pickle(ROOT / "data" / "v3" / "fees" / "historical_fee_rules.pkl")
print("="*60)
print("fee_rules", fr.shape, list(fr.columns))
print(fr.head(5).to_string())
print(fr.tail(3).to_string())

# recorded CSVs headers
OUT = ROOT / "outputs" / "v4_2_20260903_091241"
for label in ["G1__single_20_skip5", "G2__single_250", "S1__strategy_sleeve_20skip5_250_equal_risk"]:
    for n in ["scores", "selections", "directions", "targets"]:
        p = OUT / label / f"{n}.csv"
        if p.exists():
            df = pd.read_csv(p, nrows=3)
            print("="*60)
            print(label, n, "cols:", list(df.columns))
            print(df.to_string())
