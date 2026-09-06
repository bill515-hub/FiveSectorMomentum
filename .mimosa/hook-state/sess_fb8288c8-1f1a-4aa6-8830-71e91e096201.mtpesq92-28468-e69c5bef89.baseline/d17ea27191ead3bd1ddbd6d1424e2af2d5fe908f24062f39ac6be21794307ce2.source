"""D2 + M4: merge real daily margin rates from fee raw into normalized bars.

Read-only w.r.t. the original repo (operates on the rerun copy's bars.pkl).
T margin rates are stored as percentages (2.0 = 2%); convert by /100.
Other instruments are already decimal fractions (0.07 = 7%).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

bars_path = Path("data/normalized_v2/bars.pkl")
fee_raw_path = Path("data/v3/fees/tushare_fut_settle_daily_raw.pkl")

bars = pd.read_pickle(bars_path)
raw = pd.read_pickle(fee_raw_path)
u = raw[raw["source_status"].eq("tushare")].copy()
u["date"] = pd.to_datetime(u["trade_date"], errors="coerce")
u = u.dropna(subset=["date"])
u["ts_code"] = u["ts_code"].astype(str)

# Normalize margin units: T is percent (2.0 -> 0.02); others already decimal.
for col in ["long_margin_rate", "short_margin_rate"]:
    u[col] = pd.to_numeric(u[col], errors="coerce")
t_mask = u["instrument"].eq("T")
u.loc[t_mask, ["long_margin_rate", "short_margin_rate"]] = (
    u.loc[t_mask, ["long_margin_rate", "short_margin_rate"]] / 100.0
)

merge = u[["ts_code", "date", "long_margin_rate", "short_margin_rate"]].drop_duplicates(["ts_code", "date"])
bars["date"] = pd.to_datetime(bars["date"])
bars = bars.merge(merge, on=["ts_code", "date"], how="left")

print("bars rows:", len(bars))
print("long_margin_rate non-null:", int(bars["long_margin_rate"].notna().sum()))
print("short_margin_rate non-null:", int(bars["short_margin_rate"].notna().sum()))
for inst in ["RB", "T", "AL"]:
    s = bars[bars["instrument"].eq(inst)]
    vals = sorted({round(float(x), 4) for x in s["long_margin_rate"].dropna().unique()})
    print(f"{inst} long_margin distinct={vals}")

bars.to_pickle(bars_path)
print("wrote", bars_path)
