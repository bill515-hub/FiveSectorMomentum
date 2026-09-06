# -*- coding: utf-8 -*-
"""锁板两实现对账：T2b(仅主力映射锁板日) vs 实现B(任意合约锁板日成交) 逐笔合并。"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（已入 pre_manifest 哈希快照）

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"

daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])

lock_dir = {}
for r in daily.itertuples(index=False):
    if pd.notna(r.high) and pd.notna(r.low) and r.high == r.low and (r.vol and r.vol > 0):
        mark = r.settle if pd.notna(r.settle) else r.close
        lock_dir[(r.trade_date, r.ts_code)] = np.sign(mark - r.pre_settle) if pd.notna(r.pre_settle) else 0.0

mapped_pairs = set(zip(mapping["date"], mapping["contract"]))

rows = []
for run_name, p in [("v3", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl"),
                    ("S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")]:
    f = read_pickle(p)
    f["date"] = pd.to_datetime(f["date"])
    for r in f.itertuples(index=False):
        key = (r.date, r.contract)
        if key in lock_dir:
            d = lock_dir[key]
            adverse = (r.quantity > 0 and d > 0) or (r.quantity < 0 and d < 0)
            rows.append({
                "run": run_name, "date": str(r.date.date()), "contract": r.contract,
                "quantity": r.quantity, "reason": getattr(r, "reason", ""),
                "is_mapped_that_day": key in mapped_pairs,
                "board": "涨停" if d > 0 else "跌停",
                "adverse": bool(adverse),
                "in_T2b_scope": bool(key in mapped_pairs),  # T2b 只统计映射锁板日
            })
out = pd.DataFrame(rows)
out.to_csv(TMP / "locked_scope_reconciliation.csv", index=False, encoding="utf-8-sig")
print(out.to_string(index=False))
print("\n按口径汇总：")
print("  全部锁板成交分段:", len(out), " 其中逆方向:", int(out.adverse.sum()))
sub = out[out.is_mapped_that_day]
print("  仅主力映射锁板日分段:", len(sub), " 其中逆方向:", int(sub.adverse.sum()))
print("  非映射合约锁板日分段:", len(out) - len(sub), " 其中逆方向:", int(out[~out.is_mapped_that_day].adverse.sum()))
