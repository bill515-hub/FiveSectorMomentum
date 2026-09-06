# -*- coding: utf-8 -*-
"""v6.1 结果独立审计（只读；输出到 verify_20260903/tmp）。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl，属受审计既有内容）。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
V61 = ROOT / "outputs/v6_1_20260906_155224"
V3 = ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline"
S1 = ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk"
TMP = ROOT / "verify_20260903" / "tmp"

log = []
def emit(s=""):
    print(s); log.append(str(s))

# ---------- 1. R01/R02 兼容锚逐笔比对 ----------
for tag, v61_dir, legacy_dir in [("R01 vs v3", V61 / "R01", V3), ("R02 vs S1", V61 / "R02", S1)]:
    f_new = read_pickle(v61_dir / "fills.pkl"); f_old = read_pickle(legacy_dir / "fills.pkl")
    keys = ["date", "created_date", "contract", "quantity", "transaction_type"]
    for c in ["date", "created_date"]:
        f_new[c] = pd.to_datetime(f_new[c]); f_old[c] = pd.to_datetime(f_old[c])
    cols = [c for c in ["price", "commission", "slippage_cost", "traded_notional"] if c in f_new and c in f_old]
    a = f_new[keys + cols].sort_values(keys).reset_index(drop=True)
    b = f_old[keys + cols].sort_values(keys).reset_index(drop=True)
    same_shape = a.shape == b.shape
    if same_shape and len(a):
        max_price = float((a["price"] - b["price"]).abs().max())
        max_comm = float((a["commission"] - b["commission"]).abs().max())
        n_equal = int((a[keys].reset_index(drop=True) == b[keys].reset_index(drop=True)).all(axis=1).sum())
        emit(f"[兼容锚] {tag}: 行数 {len(a)}=={len(b)}={same_shape}, 键全等行={n_equal}/{len(a)}, "
             f"price最大差={max_price:.6g}, commission最大差={max_comm:.6g}")
    else:
        emit(f"[兼容锚] {tag}: 形状不一致 new={a.shape} old={b.shape}")

# ---------- 2. P03 vs R01 差异分解要素 ----------
r1 = read_pickle(V61 / "R01" / "fills.pkl"); p3 = read_pickle(V61 / "P03" / "fills.pkl")
for f in (r1, p3):
    f["date"] = pd.to_datetime(f["date"]); f["created_date"] = pd.to_datetime(f["created_date"])
emit(f"\n[P03 vs R01] fills {len(p3)} vs {len(r1)}; commission {p3.commission.sum():,.0f} vs {r1.commission.sum():,.0f}; "
     f"slippage {p3.slippage_cost.sum():,.0f} vs {r1.slippage_cost.sum():,.0f}")
# 基础滑点分层核查
tick_cols = [c for c in p3.columns if "tick" in c.lower()]
emit(f"P03 fills tick 相关列: {tick_cols}")
if "base_slippage_ticks" in p3.columns:
    by_inst = p3.groupby("instrument")["base_slippage_ticks"].agg(["mean", "min", "max"])
    emit("P03 base_slippage_ticks 按品种(前12)：\n" + by_inst.head(12).to_string())
if "reason" in p3.columns:
    emit("P03 slippage 按原因:\n" + p3.groupby("reason")["slippage_cost"].sum().to_string())
    emit("R01 slippage 按原因:\n" + r1.groupby("reason")["slippage_cost"].sum().to_string())

# ---------- 3. 出界/一价拒单假想盈亏（选择性偏差定量） ----------
rej = read_pickle(V61 / "P03" / "rejections.pkl")
rej["date"] = pd.to_datetime(rej["date"]); rej["created_date"] = pd.to_datetime(rej["created_date"])
emit(f"\n[P03 拒单] 总数={len(rej)}, 原因分布:\n{rej['reason'].value_counts().to_string() if 'reason' in rej else rej.columns.tolist()}")
daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
bars = daily.set_index(["trade_date", "ts_code"])[["open", "high", "low", "close", "settle", "vol"]]
meta = read_pickle(ROOT / "data/normalized_v2/contract_meta.pkl")
pv_map = dict(zip(meta["ts_code"], meta["point_value"]))
tick_map = dict(zip(meta["ts_code"], meta["tick_size"]))
mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])
# 每品种当日主力合约（用于把拒单映射到实际可成交合约）
main_by_day = {(r.date, r.instrument): r.contract for r in mapping.itertuples(index=False)}

rows = []
for r in rej.itertuples(index=False):
    reason = getattr(r, "reason", "")
    qty = getattr(r, "quantity_remaining", None)
    if qty is None or qty == 0 or pd.isna(qty):
        continue
    inst = getattr(r, "instrument", None)
    # 找该订单对应合约：优先 order 里的 contract 字段
    contract = getattr(r, "contract", None)
    if not contract or pd.isna(contract):
        contract = main_by_day.get((r.date, inst))
    key = (r.date, contract)
    if key not in bars.index or inst is None or pd.isna(inst):
        continue
    bar = bars.loc[key]
    o, h, l, st = float(bar["open"]), float(bar["high"]), float(bar["low"]), float(bar["settle"])
    pv = float(pv_map.get(contract, 1.0)); tick = float(tick_map.get(contract, 1.0))
    side = 1 if qty > 0 else -1
    # 假想成交价：open + 正常基础滑点(1 or 2 tick by tier) + roll 1 tick if reason==roll
    base = 1.0 if inst in ("T", "RB", "AL") else 2.0
    roll = 1.0 if reason == "roll" else 0.0
    fill = o + side * (base + roll) * tick
    # 假想持仓至周五/次周五（近似持有到该周最后交易日结算）——用 5 个交易日后结算价近似
    idx = bars.index.get_indexer([key])[0]
    # 简化：用当日结算与 5 日后结算（同合约）
    future_key = None
    dates_same_contract = bars.xs(contract, level=1).index
    pos = dates_same_contract.get_indexer([r.date])
    if len(pos) and pos[0] >= 0 and pos[0] + 5 < len(dates_same_contract):
        future_date = dates_same_contract[pos[0] + 5]
        st5 = float(bars.loc[(future_date, contract), "settle"])
    else:
        st5 = st
    first_day = (st - fill) * side * abs(qty) * pv          # 首日 盯市盈亏
    five_day = (st5 - fill) * side * abs(qty) * pv          # 5日 盯市盈亏
    rows.append({"date": str(r.date.date()), "instrument": inst, "contract": contract,
                 "reason": reason, "qty": qty, "open": o, "high": h, "low": l, "settle": st,
                 "hypothetical_fill": fill, "first_day_pnl": first_day, "five_day_pnl": five_day})
hyp = pd.DataFrame(rows)
if len(hyp):
    emit(f"\n[假想盈亏] 可评估拒单 {len(hyp)} 条")
    emit(f"  首日假想盈亏: 合计={hyp.first_day_pnl.sum():+,.0f}, 均值={hyp.first_day_pnl.mean():+,.0f}, "
         f"亏损笔占比={(hyp.first_day_pnl<0).mean()*100:.1f}%")
    emit(f"  5日假想盈亏: 合计={hyp.five_day_pnl.sum():+,.0f}, 均值={hyp.five_day_pnl.mean():+,.0f}, "
         f"亏损笔占比={(hyp.five_day_pnl<0).mean()*100:.1f}%")
    emit("  按原因分解(首日):\n" + hyp.groupby("reason")["first_day_pnl"].agg(["count", "sum", "mean"]).to_string())
    hyp.to_csv(TMP / "v61_rejected_hypothetical_pnl.csv", index=False, encoding="utf-8-sig")

# ---------- 4. AL 集中度 R02 vs P04 ----------
for tag, d in [("R02", V61 / "R02"), ("P04", V61 / "P04")]:
    p = read_pickle(d / "pnl_by_instrument.pkl")
    by = p.groupby("instrument")["net_pnl"].sum().sort_values()
    pos = by[by > 0]
    al = float(by.get("AL", 0.0))
    emit(f"\n[{tag}] AL净贡献={al:,.0f}, 正利润合计={pos.sum():,.0f}, AL占正利润={al/pos.sum()*100:.1f}%")

# ---------- 5. P03 会计独立复算 ----------
eq = read_pickle(V61 / "P03" / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
f_p3 = p3
prev = eq["equity"].shift(1).fillna(10_000_000.0)
r_eq = float((eq["equity"] - prev - eq["net_pnl"]).abs().max())
r_gf = float((eq["net_pnl"] - (eq["gross_pnl"] - eq["fees"])).abs().max())
r_fee = float(abs(f_p3["commission"].sum() - eq["fees"].sum()))
emit(f"\n[P03 会计] 逐日残差={r_eq:.2e}, 毛-费=净残差={r_gf:.2e}, fills费=账面费差={r_fee:.2e}")

(TMP / "v61_result_audit_report.txt").write_text("\n".join(log), encoding="utf-8")
emit("\nDONE")
