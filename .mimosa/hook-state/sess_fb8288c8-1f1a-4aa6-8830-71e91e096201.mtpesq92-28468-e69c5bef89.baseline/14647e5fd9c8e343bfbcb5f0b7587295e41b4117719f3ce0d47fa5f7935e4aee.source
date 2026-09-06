# -*- coding: utf-8 -*-
"""T8 参考引擎重实现（端到端金标准）。

输入（全部只读仓库既有数据）：
  - v3 正式基准 orders.pkl（订单流外生：已定信号与目标）
  - fut_daily.pkl / contract_meta.pkl / mapping.pkl
自实现执行内核：t 日订单 → t+1 日开盘成交（分层tick滑点 + 换月tick + 参与率冲击 + 不利网格取整 +
参与率上限=滞后中位量×5%，cancel 模式一日有效）→ 结算盯市 → 逐日权益。
不复用框架任何模块。手续费按订单键匹配框架逐段值（隔离执行层差异），未匹配段用 T1 的 /10000 口径。
"""
import math
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（已入 pre_manifest 哈希快照）

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

INITIAL = 10_000_000.0
HIGH_NAMES = {"T", "RB", "AL"}
HIGH_MIN_VOL, HIGH_MIN_OI = 10_000.0, 20_000.0
PART_CAP, FALLBACK_VOL = 0.05, 10_000.0
ROLL_TICK = 1.0

daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
bar = {}
for r in daily.itertuples(index=False):
    bar[(r.trade_date, r.ts_code)] = dict(open=r.open, high=r.high, low=r.low, close=r.close,
                                          settle=r.settle, vol=r.vol, oi=r.oi)

meta = read_pickle(ROOT / "data/normalized_v2/contract_meta.pkl")
pv_map = dict(zip(meta["ts_code"], meta["point_value"]))
tick_map = dict(zip(meta["ts_code"], meta["tick_size"]))
inst_map = dict(zip(meta["ts_code"], meta["instrument"]))

mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])
START, END = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-08-31")
all_dates = sorted(d for d in mapping["date"].unique() if START <= d <= END)
date_idx = {d: i for i, d in enumerate(all_dates)}

# ---- 滞后流动性中位量（自实现：映射合约成交量的 20 日滚动中位，min10） ----
vol_series, oi_series = {}, {}
for inst, g in mapping.groupby("instrument"):
    g = g.sort_values("date")
    v, o = [], []
    for r in g.itertuples(index=False):
        b = bar.get((r.date, r.contract), {})
        v.append(b.get("vol", np.nan)); o.append(b.get("oi", np.nan))
    s = pd.DataFrame({"date": g["date"].to_numpy(), "vol": v, "oi": o}).set_index("date").sort_index()
    vol_series[inst] = s["vol"].rolling(20, min_periods=10).median()
    oi_series[inst] = s["oi"].rolling(20, min_periods=10).median()

orders = read_pickle(ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/orders.pkl")
orders["created_date"] = pd.to_datetime(orders["created_date"])
orders_by_day = {}
for r in orders.itertuples(index=False):
    orders_by_day.setdefault(r.created_date, []).append(r)

fw_fills = read_pickle(ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl")
fw_fills["date"] = pd.to_datetime(fw_fills["date"])
fw_fills["created_date"] = pd.to_datetime(fw_fills["created_date"])
# 执行级费用（框架一次执行可拆多段，先聚合到执行键）
fw_comm = (fw_fills.groupby(["created_date", "date", "contract"])["commission"].sum().to_dict())

# T1 口径费用函数（/10000 框架口径；仅用于未匹配段）
fee_raw = read_pickle(ROOT / "data/v3/fees/tushare_fut_settle_daily_raw.pkl")
fee_raw["trade_date"] = pd.to_datetime(fee_raw["trade_date"], errors="coerce")
fee_raw = fee_raw[fee_raw["source_status"].eq("tushare")]
fee_map_t1 = {}
for r in fee_raw.itertuples(index=False):
    if pd.isna(r.trade_date):
        continue
    fee_map_t1[(r.instrument, r.trade_date)] = (r.trading_fee, r.trading_fee_rate)
last_std = {}
for inst, g in fee_raw.groupby("instrument"):
    g = g.sort_values("trade_date")
    last = g.iloc[-1]
    last_std[inst] = (last.trading_fee, last.trading_fee_rate)

def my_fee(inst, d, qty, price, pv):
    fee, rate = fee_map_t1.get((inst, d), last_std.get(inst, (0.0, 0.0)))
    fee = fee if fee is not None and pd.notna(fee) else 0.0
    rate = rate if rate is not None and pd.notna(rate) else 0.0
    if inst == "T" and fee == 0 and rate > 0:
        per_lot, dec = rate, 0.0
    elif rate > 0 and fee == 0:
        per_lot, dec = 0.0, rate / 10000.0
    else:
        per_lot, dec = fee, 0.0
    return abs(qty) * (per_lot + price * pv * dec) * 1.5

# ---- 主循环 ----
positions = {}
prev_mark = {}
my_fills = []
my_rejections = []
equity = INITIAL
equity_rows = []
pending = []

for d in all_dates:
    i = date_idx[d]
    day_fills = []
    for order in pending:
        contract = order.contract; qty = order.quantity
        key = (d, contract)
        b = bar.get(key)
        if b is None or pd.isna(b["open"]):
            my_rejections.append((d, contract, qty, "missing_bar_or_no_open")); continue
        inst = order.instrument
        mv = vol_series[inst].get(d if False else order.created_date, np.nan)
        mo = oi_series[inst].get(order.created_date, np.nan)
        available = float(mv) if pd.notna(mv) and mv > 0 else FALLBACK_VOL
        maximum = max(0, int(math.floor(available * PART_CAP)))
        fill_abs = min(abs(qty), maximum)
        if fill_abs == 0:
            my_rejections.append((d, contract, qty, "participation_limit")); continue
        fill_qty = int(math.copysign(fill_abs, qty))
        participation = fill_abs / available
        base = 1.0 if (inst in HIGH_NAMES and pd.notna(mv) and mv >= HIGH_MIN_VOL
                       and pd.notna(mo) and mo >= HIGH_MIN_OI) else 2.0
        roll = ROLL_TICK if order.reason == "roll" else 0.0
        impact = 0.0 if participation <= 0.01 else (1.0 if participation <= 0.03 else 2.0)
        total_ticks = base + roll + impact
        tick = float(tick_map.get(contract, 1.0))
        raw = float(b["open"]) + math.copysign(total_ticks * tick, fill_qty)
        units = raw / tick
        snapped = math.ceil(units - 1e-10) if fill_qty > 0 else math.floor(units + 1e-10)
        price = float(round(snapped * tick, 10))
        pv = float(pv_map.get(contract, 1.0))
        comm = fw_comm.get((order.created_date, d, contract))
        comm_is_fw = comm is not None
        if comm is None:
            comm = my_fee(inst, d, fill_qty, price, pv)
        positions[contract] = positions.get(contract, 0) + fill_qty
        day_fills.append(dict(created_date=order.created_date, date=d, contract=contract, instrument=inst,
                              quantity=fill_qty, order_quantity=qty, price=price, open=float(b["open"]),
                              base=base, roll=roll, impact=impact, commission=comm,
                              commission_from_framework=comm_is_fw, reason=order.reason))
        remainder = qty - fill_qty
        if remainder:
            my_rejections.append((d, contract, remainder, "partial_fill"))
    pending = []
    # 盯市
    gross = 0.0; fees = 0.0
    touched = set(positions) | {f["contract"] for f in day_fills}
    for c in sorted(touched):
        b = bar.get((d, c))
        if b is None:
            continue
        mark = float(b["settle"]) if (pd.notna(b["settle"]) and b["settle"] > 0) else float(b["close"])
        pv = float(pv_map.get(c, 1.0))
        prev_pos = positions.get(c, 0) - sum(f["quantity"] for f in day_fills if f["contract"] == c)
        prev = prev_mark.get(c)
        if prev_pos and prev is not None and np.isfinite(mark):
            gross += prev_pos * (mark - prev) * pv
        for f in [x for x in day_fills if x["contract"] == c]:
            gross += f["quantity"] * (mark - f["price"]) * pv
            fees += f["commission"]
        if prev_pos or any(x["contract"] == c for x in day_fills):
            prev_mark[c] = mark
    equity += gross - fees
    equity_rows.append(dict(date=d, equity=equity, gross_pnl=gross, fees=fees, net_pnl=gross - fees))
    my_fills.extend(day_fills)
    # 次日订单
    for order in orders_by_day.get(d, []):
        pending.append(order)

my_f = pd.DataFrame(my_fills)
my_eq = pd.DataFrame(equity_rows)

# ---- 对比（按订单执行聚合：框架把一次执行拆为 open/close 等 lot-ledger 分段） ----
fw_exec = (fw_fills.groupby(["created_date", "date", "contract"], as_index=False)
           .agg(qty_fw=("quantity", "sum"), commission_fw=("commission", "sum"),
                price_fw=("price", "first"), reason_fw=("reason", "first")))
my_exec = my_f[["created_date", "date", "contract", "quantity", "price", "commission", "reason"]] \
    .rename(columns={"quantity": "qty_my", "price": "price_my", "commission": "commission_my", "reason": "reason_my"})
merged = fw_exec.merge(my_exec, on=["created_date", "date", "contract"], how="outer", indicator=True)
both = merged[merged["_merge"].eq("both")].copy()
both["qty_diff"] = both["qty_fw"] - both["qty_my"]
both["price_diff"] = both["price_fw"] - both["price_my"]
only_fw = merged[merged["_merge"].eq("left_only")]
only_my = merged[merged["_merge"].eq("right_only")]
emit(f"按订单执行聚合: 框架执行数={len(fw_exec)}, 我的执行数={len(my_exec)}, 双侧={len(both)}, "
     f"仅框架={len(only_fw)}, 仅我的={len(only_my)}")
if len(both):
    same_qty = int((both["qty_diff"] == 0).sum())
    same_price = int((both["price_diff"].abs() < 1e-9).sum())
    emit(f"数量一致: {same_qty}/{len(both)}; 价格一致: {same_price}/{len(both)}; 价格最大差={both['price_diff'].abs().max():.6g}")
    bad = both[(both["qty_diff"] != 0) | (both["price_diff"].abs() >= 1e-9)]
    bad.to_csv(TMP / "reference_fills_diff.csv", index=False, encoding="utf-8-sig")
    emit(f"不一致执行 {len(bad)} 个已存 reference_fills_diff.csv")
    if len(bad):
        emit(bad[["created_date", "date", "contract", "qty_fw", "qty_my", "reason_fw"]].head(10).to_string(index=False))
if len(only_fw):
    only_fw.to_csv(TMP / "reference_fills_only_fw.csv", index=False, encoding="utf-8-sig")
    emit(f"仅框架存在的执行 {len(only_fw)} 个已存")
if len(only_my):
    only_my.to_csv(TMP / "reference_fills_only_my.csv", index=False, encoding="utf-8-sig")
    emit(f"仅我方存在的执行 {len(only_my)} 个已存")

fw_eq = read_pickle(ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/daily_equity.pkl")
fw_eq["date"] = pd.to_datetime(fw_eq["date"])
cmp_eq = fw_eq[["date", "equity"]].merge(my_eq[["date", "equity"]], on="date", suffixes=("_fw", "_my"))
cmp_eq["diff"] = cmp_eq["equity_fw"] - cmp_eq["equity_my"]
cmp_eq.to_csv(TMP / "reference_equity_diff.csv", index=False, encoding="utf-8-sig")
emit(f"\n逐日权益对比: 天数={len(cmp_eq)}, 最大差={cmp_eq['diff'].abs().max():,.2f} 元, "
     f"末端差={cmp_eq['diff'].iloc[-1]:+,.2f} 元")
emit(f"框架期末权益={fw_eq['equity'].iloc[-1]:,.2f}, 我的期末权益={my_eq['equity'].iloc[-1]:,.2f}")
worst = cmp_eq.loc[cmp_eq["diff"].abs().idxmax()]
emit(f"最大差异日: {worst['date'].date()} 差 {worst['diff']:+,.2f}")

# 差异首日定位
first_diff = cmp_eq[cmp_eq["diff"].abs() > 0.01]
emit(f"|diff|>0.01元的天数={len(first_diff)}" + (f"，首日={first_diff['date'].iloc[0].date()}" if len(first_diff) else ""))

my_f.to_csv(TMP / "reference_engine_fills.csv", index=False, encoding="utf-8-sig")
my_eq.to_csv(TMP / "reference_engine_equity.csv", index=False, encoding="utf-8-sig")

(REPORTS / "T8_reference_engine.md").write_text(
    "# T8 参考引擎重实现 vs v3 正式基准\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT8 DONE")
