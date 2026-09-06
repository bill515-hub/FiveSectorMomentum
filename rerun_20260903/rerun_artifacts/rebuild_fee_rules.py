import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from five_sector_momentum.costs_v3 import build_fee_rules
from five_sector_momentum.storage import read_frame

raw = read_frame("data/v3/fees/tushare_fut_settle_daily_raw")
mapping = read_frame("data/normalized_v2/mapping")
rules, cov = build_fee_rules(raw, mapping, "data/v3/fees")

print("rules rows:", len(rules))
for inst in ["RB", "SP", "T", "RU", "AL", "SC"]:
    sub = rules[rules["instrument"].eq(inst) & rules["trade_type"].eq("open")]
    rates = sorted({round(float(x), 8) for x in sub["fee_rate"].unique()})
    lots = sorted({round(float(x), 4) for x in sub["fee_per_lot"].unique()})
    print(f"{inst}: fee_rate={rates} fee_per_lot={lots}")
