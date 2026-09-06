# -*- coding: utf-8 -*-
"""T1 费率单位审计 + 独立影响重算（独立实现：不 import five_sector_momentum，不复用旧审计脚本）。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身数据文件（已纳入 pre_manifest 哈希快照）。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "verify_20260903"
TMP = OUT / "tmp"
REPORTS = OUT / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

raw = pd.read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
raw["trade_date"] = pd.to_datetime(raw["trade_date"], errors="coerce")
usable = raw[raw["source_status"].eq("tushare")].copy()
emit(f"fee raw rows={len(raw)}, usable(source_status==tushare)={len(usable)}")

for col in ["trading_fee", "trading_fee_rate"]:
    usable[col] = pd.to_numeric(usable[col], errors="coerce")

# ---- 特例识别：trading_fee 缺失/0 且 rate>0 且 CFFEX ----
fee_zero = usable["trading_fee"].isna() | usable["trading_fee"].fillna(0).eq(0)
special_mask = fee_zero & usable["trading_fee_rate"].fillna(0).gt(0) & usable["exchange"].eq("CFFEX")
special_insts = sorted(usable.loc[special_mask, "instrument"].unique())
emit(f"\n特例(CFFEX rate字段=元/手): {special_insts}")
for inst in special_insts:
    vals = usable.loc[special_mask & usable["instrument"].eq(inst), "trading_fee_rate"]
    emit(f"  {inst}: rate field distinct={sorted(vals.unique())}, n={len(vals)}")

# ---- 真费率型：rate>0 且 fee 缺失/0 的非 CFFEX ----
rate_mask = fee_zero & usable["trading_fee_rate"].fillna(0).gt(0) & ~usable["exchange"].eq("CFFEX")
rate_insts = sorted(usable.loc[rate_mask, "instrument"].unique())
emit(f"\n真费率型(rate>0 & fee缺/0 & 非CFFEX): {rate_insts}")
emit(f"对照：RU 固定3元是否被正确排除: {'RU' not in rate_insts}")

# 各品种全景：distinct fee / rate
rows = []
for inst, g in usable.groupby("instrument"):
    fees = sorted(g["trading_fee"].dropna().unique())
    rates = sorted(g["trading_fee_rate"].dropna().unique())
    kind = ("CFFEX_rate_as_perlot" if inst in special_insts else
            "rate_based" if inst in rate_insts else "fixed_per_lot")
    rows.append({"instrument": inst, "kind": kind, "exchange": g["exchange"].iloc[0],
                 "n_rows": len(g), "distinct_trading_fee": fees[:8], "distinct_trading_fee_rate": rates[:8],
                 "first_date": str(g.trade_date.min().date()), "last_date": str(g.trade_date.max().date())})
overview = pd.DataFrame(rows)
overview.to_csv(TMP / "fee_rate_distinct_by_instrument.csv", index=False, encoding="utf-8-sig")
emit("\n=== fee kind overview ===")
emit(overview[["instrument","kind","exchange","n_rows","distinct_trading_fee","distinct_trading_fee_rate"]].to_string(index=False))

# 费率型品种的生效区间
emit("\n=== rate-based instruments: 生效区间 ===")
for inst in rate_insts:
    g = usable[usable["instrument"].eq(inst) & rate_mask[usable["instrument"].eq(inst)].fillna(False)]
    g = g.sort_values("trade_date")
    for v, sub in g.groupby("trading_fee_rate"):
        emit(f"  {inst}: rate={v} 从 {sub.trade_date.min().date()} 到 {sub.trade_date.max().date()} (n={len(sub)})")
        emit(f"    /1000 => {v/1000:.6f} (={v/10:.4f}bp) ; /10000 => {v/10000:.6f} (={v/100:.4f}bp)")
        emit(f"    官方对照: 万分之{v*10:g}（/1000 口径）vs 万分之{v:g}（/10000 口径）")

# ---- 独立重算：逐 fill 重算手续费 ----
def build_fee_map():
    """(instrument, trade_date) -> dict(rate, fee, special)"""
    m = {}
    for r in usable.itertuples(index=False):
        inst = r.instrument
        d = r.trade_date
        if pd.isna(d):
            continue
        m[(inst, d)] = {"rate": r.trading_fee_rate, "fee": r.trading_fee,
                        "special": bool(inst in special_insts)}
    return m

fee_map = build_fee_map()

def last_standard(inst):
    """品种最新观测标准（代理口径，用于无 raw 行的日期——与框架 proxy_latest_instrument 对齐）。"""
    g = usable[usable["instrument"].eq(inst)].sort_values("trade_date")
    if g.empty:
        return {"rate": 0.0, "fee": 0.0, "special": inst in special_insts}
    last = g.iloc[-1]
    return {"rate": float(last.trading_fee_rate) if pd.notna(last.trading_fee_rate) else 0.0,
            "fee": float(last.trading_fee) if pd.notna(last.trading_fee) else 0.0,
            "special": inst in special_insts}

def recompute_fills(fills_path, divisor):
    f = pd.read_pickle(fills_path)
    f["date"] = pd.to_datetime(f["date"])
    diffs = []
    total_exch = 0.0; total_client = 0.0; framework_total = float(f.commission.sum())
    for r in f.itertuples(index=False):
        rec = fee_map.get((r.instrument, r.date)) or last_standard(r.instrument)
        rate_val = rec["rate"] if rec["rate"] is not None and pd.notna(rec["rate"]) else 0.0
        fee_val = rec["fee"] if rec["fee"] is not None and pd.notna(rec["fee"]) else 0.0
        if rec["special"]:
            per_lot, rate_dec = rate_val, 0.0        # T: rate 字段数值=元/手
        elif rate_val > 0 and fee_val == 0:
            per_lot, rate_dec = 0.0, rate_val / divisor  # 真费率型
        else:
            per_lot, rate_dec = fee_val, 0.0            # 固定每手
        exch = abs(r.quantity) * (per_lot + r.price * r.point_value * rate_dec)
        client = exch * 1.5
        total_exch += exch; total_client += client
        diffs.append(client - float(r.commission))
    f["recomputed_client"] = f.commission + np.array(diffs)
    return f, total_client, framework_total

impact_rows = []
for label, p in [("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl"),
                 ("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")]:
    for divisor, tag in [(1000, "千分数/1000"), (10000, "万分数/10000(框架现行)")]:
        f2, mine, fw = recompute_fills(p, divisor)
        impact_rows.append({
            "run": label, "口径": tag, "framework_commission": fw,
            "recomputed_commission": mine, "difference": mine - fw,
            "abs_mean_per_fill_diff": (f2.recomputed_client - f2.commission).abs().mean(),
            "max_abs_per_fill_diff": (f2.recomputed_client - f2.commission).abs().max(),
        })
        emit(f"\n{label} [{tag}]: framework={fw:,.0f}  recomputed={mine:,.0f}  diff={mine-fw:+,.0f}")
    # 逐笔差异分布（/1000 口径）
    f3, _, _ = recompute_fills(p, 1000)
    d = (f3.recomputed_client - f3.commission)
    emit(f"  /1000 口径逐笔差: mean={d.mean():+.2f}, p95={d.quantile(.95):+.2f}, 最大={d.max():+.2f}; 差异笔数(>0.01元)={int((d.abs()>0.01).sum())}/{len(d)}")
    f3.to_csv(TMP / f"fills_fee_recompute_{label}.csv", index=False, encoding="utf-8-sig")

impact = pd.DataFrame(impact_rows)
impact.to_csv(TMP / "fee_impact_recompute.csv", index=False, encoding="utf-8-sig")
emit("\n" + impact.to_string(index=False))

(REPORTS / "T1_recompute.md").write_text(
    "# T1 费率单位审计 + 独立影响重算\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT1 DONE")
