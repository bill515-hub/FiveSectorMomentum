import pandas as pd, numpy as np
from pathlib import Path

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "outputs" / "v4_2_20260903_091241"
DATA = ROOT / "data" / "normalized_v2"

def show(name, df):
    print("="*80)
    print(name, "shape", df.shape)
    print("columns", list(df.columns))
    print(df.head(3).to_string())
    print(df.tail(2).to_string())
    print("dtypes:", dict(df.dtypes.astype(str)))
    print()

# data inputs
for n in ["adjusted_prices", "bars", "mapping", "instrument_meta", "contract_meta"]:
    show("DATA "+n, pd.read_pickle(DATA / f"{n}.pkl"))

cal = pd.read_pickle(ROOT / "outputs" / "v4_2_20260903_091241" / "calendar" / "calendar_daily.pkl")
show("calendar_daily", cal)

for label in ["G1__single_20_skip5", "G2__single_250", "S1__strategy_sleeve_20skip5_250_equal_risk"]:
    for n in ["scores", "selections", "targets", "directions"]:
        p = OUT / label / f"{n}.pkl"
        if p.exists():
            show(f"{label}/{n}", pd.read_pickle(p))

for n in ["internal_targets", "net_target_stages", "risk_stages"]:
    p = OUT / "S1__strategy_sleeve_20skip5_250_equal_risk" / f"{n}.pkl"
    if p.exists():
        show("S1/"+n, pd.read_pickle(p))
