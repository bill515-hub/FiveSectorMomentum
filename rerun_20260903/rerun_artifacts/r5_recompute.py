import pathlib
import pandas as pd
import numpy as np

ROOT = pathlib.Path(r"D:\FiveSectorMomentum")
ART = ROOT / "rerun_20260903" / "rerun_artifacts"

# ---- 1. Official T fee from framework's own fee tables ----
raw_fee = pd.read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
print("raw fee cols:", list(raw_fee.columns))
raw_fee["trade_date"] = pd.to_datetime(raw_fee["trade_date"], errors="coerce")
t_raw = raw_fee[raw_fee["instrument"].astype(str).eq("T")].copy()
for col in ["trading_fee", "trading_fee_rate"]:
    t_raw[col] = pd.to_numeric(t_raw.get(col, 0.0), errors="coerce")
print("T raw rows:", len(t_raw))
print("T trading_fee distinct:", sorted(t_raw["trading_fee"].dropna().unique()))
print("T trading_fee_rate distinct:", sorted(t_raw["trading_fee_rate"].dropna().unique()))
print("T source_status distinct:", sorted(t_raw["source_status"].astype(str).unique()))
print("T exchange distinct:", sorted(t_raw["exchange"].astype(str).unique()))
print("T date range:", t_raw["trade_date"].min(), "..", t_raw["trade_date"].max())
# rows where fee field is NaN but rate>0 (schema drift documented in costs_v3)
t_special = t_raw[t_raw["trading_fee"].isna() & t_raw["trading_fee_rate"].gt(0)]
print("T special (fee NaN & rate>0) rows:", len(t_special), "rate distinct:", sorted(t_special["trading_fee_rate"].dropna().unique()))

rules = pd.read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
t_rules = rules[rules["instrument"].astype(str).eq("T")].copy()
print("\nT fee rules rows:", len(t_rules))
print(t_rules[["contract","instrument","trade_type","effective_from","effective_to","fee_per_lot","fee_rate","source_type"]].head(12).to_string(index=False))
t_open = t_rules[(t_rules["trade_type"]=="open") & (t_rules["contract"]!="*")]
print("\nT open rules distinct fee_per_lot:", sorted(t_open["fee_per_lot"].dropna().unique()))
print("T open rules distinct fee_rate:", sorted(t_open["fee_rate"].dropna().unique()))

# ---- 2. v1/v2 raw fut_settle used by v1/v2 pipeline ----
v1_settle = ROOT / "data/raw/tushare/fut_settle.pkl"
if v1_settle.exists():
    s = pd.read_pickle(v1_settle)
    print("\nv1/v2 data/raw/tushare/fut_settle.pkl:", type(s).__name__)
    try:
        print("shape:", s.shape, "cols:", list(s.columns))
    except Exception as e:
        print("no shape/cols:", e)
        print(s)

# ---- 3. FALLBACK economics for T ----
import ast, re
uni = (ROOT / "src/five_sector_momentum/universe.py").read_text(encoding="utf-8")
m = re.search(r'"T":\s*\(([^)]*)\)', uni)
print("\nuniverse.py FALLBACK_ECONOMICS T tuple:", m.group(0) if m else "NOT FOUND")

# ---- 4. Load fills and recompute ----
runs = {
    "v1_final": ROOT / "outputs/20260901_180546",
    "v2_final": ROOT / "outputs/v2_20260901_213543",
}
scenarios = {
    "v1_baseline": "vol_0p275__cancel_recalculate__slip_2p0t",
    "v2_baseline": "vol_0p275__cancel_recalculate__slip_2p0t",
}
print("\n" + "="*100)
for run_name, run_root in runs.items():
    for sd in sorted([p for p in run_root.iterdir() if p.is_dir()]):
        fp = sd / "fills.pkl"
        if not fp.exists():
            continue
        f = pd.read_pickle(fp)
        cols = list(f.columns)
        t = f[f["instrument"].astype(str).str.upper().eq("T")].copy()
        if len(t) == 0:
            continue
        lots = t["quantity"].abs().sum()
        comm = t["commission"].sum()
        per_lot = comm / lots
        # recorded fallback check using T point value 10000 (FALLBACK_ECONOMICS)
        pv = 10000.0
        fallback_term = t["price"].astype(float) * pv * 0.0002
        fallback_pred = pd.concat([pd.Series(5.0, index=t.index), fallback_term], axis=1).max(axis=1)
        fallback_pred_sum = (fallback_pred * t["quantity"].abs()).sum()
        implied_pv = t["commission"] / (t["quantity"].abs() * t["price"].astype(float) * 0.0002)
        print(f"{run_name:10s} | {sd.name:40s} | T rows={len(t):5d} lots={lots:6.0f} | "
              f"rec_comm={comm:12.2f} | per_lot={per_lot:8.4f} | "
              f"fallback_pred_sum={fallback_pred_sum:12.2f} | max|rec-fallback|/lot={((t['commission']-fallback_pred*t['quantity'].abs()).abs()/t['quantity'].abs()).max():.6f} | "
              f"price range={t['price'].min():.3f}..{t['price'].max():.3f}")
        # per-lot fallback breakdown at a few prices
        sample = t.sort_values("price").drop_duplicates("price").head(3)
        for _, r in sample.iterrows():
            print(f"      price={r['price']:.4f} -> fallback per lot={max(5.0, r['price']*pv*0.0002):.6f}, recorded/lot={r['commission']/abs(r['quantity']):.6f}")

    # baseline totals
    b = run_root / scenarios[run_name.split('_')[0] + "_baseline"] / "fills.pkl"
    if b.exists():
        f = pd.read_pickle(b)
        t = f[f["instrument"].astype(str).str.upper().eq("T")].copy()
        lots = t["quantity"].abs().sum()
        comm = t["commission"].sum()
        official_exchange = 3.0  # yuan/lot per side
        official_client = 3.0 * 1.2  # framework v1/v2 uses reported*1.2; official client basis
        over_per_lot = comm/lots - official_client
        print(f"\n>>> {run_name} BASELINE {scenarios[run_name.split('_')[0]+'_baseline']}:")
        print(f"    T lots={lots}, recorded commission={comm:.2f}, per_lot={comm/lots:.4f}")
        print(f"    official exchange 3.0/lot -> total exchange={lots*3.0:.2f}")
        print(f"    official client 3.6/lot -> total client={lots*3.6:.2f}")
        print(f"    over-statement vs client={comm - lots*3.6:.2f} (ratio {comm/(lots*3.6):.2f}x)")
        print(f"    over-statement vs exchange={comm - lots*3.0:.2f} (ratio {comm/(lots*3.0):.2f}x)")
