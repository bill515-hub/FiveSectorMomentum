"""M3: derive limit prices for locked-board days (high==low with volume>0).

Strategy: without ft_limit token permission, infer the binding limit price on
locked days from the settlement vs pre_settle direction.  On a limit-up locked
day the traded price is pinned at the upper limit (settlement > pre_settle); on
a limit-down locked day it is pinned at the lower limit (settlement < pre_settle).
We set ONLY the binding side so the engine's existing logic works unchanged:
  - buy  adverse when open >= upper_limit
  - sell adverse when open <= lower_limit
Non-locked days keep upper_limit/lower_limit = NaN (no clamp, no reject).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import pandas as pd

bars_path = Path("data/normalized_v2/bars.pkl")
bars = pd.read_pickle(bars_path)

bars["upper_limit"] = np.nan
bars["lower_limit"] = np.nan
bars["volume"] = pd.to_numeric(bars["volume"], errors="coerce")

locked = (bars["high"] == bars["low"]) & (bars["volume"] > 0)
up = locked & (bars["settlement"] > bars["pre_settle"])
down = locked & (bars["settlement"] < bars["pre_settle"])

bars.loc[up, "upper_limit"] = bars.loc[up, "settlement"]
bars.loc[down, "lower_limit"] = bars.loc[down, "settlement"]

print("locked days:", int(locked.sum()))
print("limit-up locked days:", int(up.sum()))
print("limit-down locked days:", int(down.sum()))
print("upper_limit non-null:", int(bars["upper_limit"].notna().sum()))
print("lower_limit non-null:", int(bars["lower_limit"].notna().sum()))

# Show the locked-day rows for a human sanity check.
locked_rows = bars[locked][
    ["ts_code", "date", "pre_settle", "open", "high", "low", "settlement", "volume", "upper_limit", "lower_limit"]
].sort_values("date")
print(locked_rows.to_string())

bars.to_pickle(bars_path)
print("wrote", bars_path)
