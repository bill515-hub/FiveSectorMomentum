import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import pandas as pd

raw = pd.read_pickle("data/v3/fees/tushare_fut_settle_daily_raw.pkl")
u = raw[raw["source_status"].eq("tushare")]
for inst in ["RB", "T", "AL", "SC", "SP", "RU"]:
    s = u[u["instrument"].eq(inst)]
    lm = sorted({round(float(x), 6) for x in s["long_margin_rate"].dropna().unique()})
    sm = sorted({round(float(x), 6) for x in s["short_margin_rate"].dropna().unique()})
    print(f"{inst}: long_margin={lm} short_margin={sm}")
