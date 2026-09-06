import sys, pathlib
import pandas as pd

ROOT = pathlib.Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "rerun_20260903" / "rerun_artifacts"

runs = {
    "v1_20260901_134350": ROOT / "outputs/20260901_134350",
    "v1_20260901_180546": ROOT / "outputs/20260901_180546",
    "v2_20260901_212436": ROOT / "outputs/v2_20260901_212436",
    "v2_20260901_213543": ROOT / "outputs/v2_20260901_213543",
}

for label, root in runs.items():
    subdirs = sorted([p for p in root.iterdir() if p.is_dir()])
    for sd in subdirs:
        fp = sd / "fills.pkl"
        if not fp.exists():
            continue
        try:
            f = pd.read_pickle(fp)
        except Exception as e:
            print(label, sd.name, "ERROR", e)
            continue
        t = f[f["instrument"].astype(str).str.upper() == "T"] if "instrument" in f.columns else pd.DataFrame()
        print("=" * 80)
        print(label, "|", sd.name, "| rows", len(f), "| cols", list(f.columns))
        if "instrument" in f.columns:
            print("instruments:", sorted(f["instrument"].astype(str).unique()))
        if len(t):
            print(f"T rows={len(t)} lots={t['quantity'].abs().sum()} commission={t['commission'].sum():.2f}")
            print(f"T per-lot commission mean={t['commission'].sum()/t['quantity'].abs().sum():.4f}")
            print(f"T price range {t['price'].min():.4f}..{t['price'].max():.4f} point_value unique {sorted(t['point_value'].dropna().unique())[:20]}")
            print(f"T traded_notional sum={t['traded_notional'].sum():.2f}")
        break  # only first subdir per run for now
