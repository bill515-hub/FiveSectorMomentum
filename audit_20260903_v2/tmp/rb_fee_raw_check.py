# -*- coding: utf-8 -*-
"""检查原始 tushare fut_settle 费用字段：RB 费率单位与逐日取值（只读仓库；输出到审计tmp）。"""
from pathlib import Path
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见信任边界说明）

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "audit_20260903_v2" / "tmp"

raw = read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="coerce")
rb = raw[raw["instrument"].eq("RB") & raw["source_status"].eq("tushare")].copy()
rb = rb.sort_values("trade_date")
print("RB raw rows:", len(rb))
print("columns:", list(rb.columns))
# 抽样看不同年份的费率值
for year in [2021, 2022, 2023, 2024, 2025, 2026]:
    sub = rb[rb.trade_date.dt.year.eq(year)]
    if len(sub):
        r = sub.iloc[len(sub)//2]
        print(f"{year}: n={len(sub)} sample {r.trade_date.date()} {r.ts_code} "
              f"trading_fee={r.trading_fee} trading_fee_rate={r.trading_fee_rate} "
              f"offset_today_fee={r.offset_today_fee}")
# 每年费率分布
rb["year"] = rb.trade_date.dt.year
summ = rb.groupby("year").agg(
    n=("trading_fee_rate", "size"),
    fee_rate_min=("trading_fee_rate", "min"), fee_rate_max=("trading_fee_rate", "max"),
    fee_min=("trading_fee", "min"), fee_max=("trading_fee", "max"))
print("\nRB per-year raw fee fields:")
print(summ.to_string())

# 同样检查 AL / SC / T 的原始字段（验证每手 vs 费率）
for inst in ["AL", "SC", "T", "SP"]:
    sub = raw[raw["instrument"].eq(inst) & raw["source_status"].eq("tushare")].copy()
    sub["trade_date"] = pd.to_datetime(sub["trade_date"], errors="coerce")
    sub = sub.sort_values("trade_date")
    if not len(sub):
        print(f"\n{inst}: no rows"); continue
    last = sub.iloc[-1]
    first = sub.iloc[0]
    print(f"\n{inst}: rows={len(sub)} first={first.trade_date.date()} "
          f"fee={first.trading_fee} rate={first.trading_fee_rate} | "
          f"last={last.trade_date.date()} fee={last.trading_fee} rate={last.trading_fee_rate}")

# 规则表里 RB 每段区间
rules = read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
rb_rules = rules[(rules.instrument.eq("RB")) & (rules.contract.ne("*")) & (rules.trade_type.eq("open"))]
rb_rules = rb_rules.sort_values("effective_from")
print("\nRB open fee rule intervals (contract=RB main series):")
cols = ["contract", "effective_from", "effective_to", "fee_per_lot", "fee_rate", "source_type"]
print(rb_rules[cols].to_string(index=False))
