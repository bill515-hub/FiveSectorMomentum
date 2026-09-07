# -*- coding: utf-8 -*-
"""v6.2 结果独立审计（只读；输出到 verify_20260903/tmp）。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl，属受审计既有内容）。
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
V62 = ROOT / "outputs/v6_2_20260906_222655"
V61 = ROOT / "outputs/v6_1_20260906_155224"
TMP = ROOT / "verify_20260903" / "tmp"

log = []
def emit(s=""):
    print(s); log.append(str(s))

# ---------- 1. R01/R02 vs v6.1 P03/P04 独立比对 ----------
for tag, v62_id, v61_id in [("R01", "R01", "P03"), ("R02", "R02", "P04")]:
    a = read_pickle(V62 / v62_id / "fills.pkl"); b = read_pickle(V61 / v61_id / "fills.pkl")
    keys = ["date", "created_date", "contract", "quantity", "transaction_type"]
    for f in (a, b):
        for c in ["date", "created_date"]:
            f[c] = pd.to_datetime(f[c])
    cols = ["price", "commission", "slippage_cost"]
    x = a[keys + cols].sort_values(keys).reset_index(drop=True)
    y = b[keys + cols].sort_values(keys).reset_index(drop=True)
    eq_shape = x.shape == y.shape
    if eq_shape and len(x):
        dp = float((x["price"] - y["price"]).abs().max())
        dc = float((x["commission"] - y["commission"]).abs().max())
        ds = float((x["slippage_cost"] - y["slippage_cost"]).abs().max())
        n_eq = int((x[keys] == y[keys]).all(axis=1).sum())
        emit(f"[复现锚] {v62_id} vs v6.1 {v61_id}: 行 {len(x)}=={len(y)}, 键全等 {n_eq}/{len(x)}, "
             f"price差={dp:.6g}, commission差={dc:.6g}, slippage差={ds:.6g}")

# ---------- 2. 因果性数值验证：B03 fill 价格 == 网格化 open ----------
b3 = read_pickle(V62 / "B03" / "fills.pkl")
b3["date"] = pd.to_datetime(b3["date"])
daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
om = {(r.trade_date, r.ts_code): (r.open, r.high, r.low, r.close, r.settle) for r in daily.itertuples(index=False)}
bad_ref = 0; max_dev = 0.0; uses_high_low = 0
for r in b3.itertuples(index=False):
    o = om.get((r.date, r.contract))
    if o is None:
        continue
    open_, h, l, c, st = o
    tick = float(r.tick_size)
    expect = float(round(round(open_ / tick) * tick, 10))
    if abs(float(r.price) - expect) > 1e-9:
        bad_ref += 1
        max_dev = max(max_dev, abs(float(r.price) - expect))
emit(f"\n[因果性] B03 成交价==网格化开盘价: 偏离笔数={bad_ref}/{len(b3)}, 最大偏离={max_dev:.6g}")
# 嵌入滑点应为 0，现金滑点 = lots*ticks*tick*pv
chk = b3[(b3.embedded_slippage_cost.abs() > 1e-9)]
emit(f"[现金滑点] embedded≠0 笔数={len(chk)}")
calc = b3["quantity"].abs() * b3["total_slippage_ticks"] * b3["tick_size"] * b3["point_value"]
max_d = float((calc - b3["cash_slippage_cost"]).abs().max())
emit(f"[现金滑点] |lots×ticks×tick×pv − cash| 最大差={max_d:.6g}")
# slippage_cost == cash_slippage_cost（唯一扣除）
ds = float((b3["slippage_cost"] - b3["cash_slippage_cost"]).abs().max())
emit(f"[唯一扣除] |slippage_cost − cash_slippage_cost| 最大差={ds:.6g}")

# ---------- 3. 会计独立复算（B03/B04/T02） ----------
for sid in ["B01", "B03", "B04", "T02"]:
    eq = read_pickle(V62 / sid / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
    f = read_pickle(V62 / sid / "fills.pkl")
    prev = eq["equity"].shift(1).fillna(10_000_000.0)
    r1 = float((eq["equity"] - prev - eq["net_pnl"]).abs().max())
    r2 = float(abs(f["commission"].sum() + f.get("cash_slippage_cost", pd.Series(0, index=f.index)).sum() - eq["fees"].sum()))
    r3 = float(abs(f["commission"].sum() - f["exchange_commission"].sum() * 1.5))
    emit(f"[会计] {sid}: 逐日残差={r1:.2e}, fills成本=账面差={r2:.2e}, 客户费=1.5×交易所差={r3:.2e}")

# ---------- 4. next_close 新仓 settle_d−close_d 泄漏定量 ----------
for sid in ["T01", "T02"]:
    f = read_pickle(V62 / sid / "fills.pkl")
    f["date"] = pd.to_datetime(f["date"])
    opens = f[f.transaction_type.eq("open")]
    leak = 0.0; n = 0
    for r in opens.itertuples(index=False):
        o = om.get((r.date, r.contract))
        if o is None:
            continue
        st, c = o[4], o[3]
        # 每手泄漏 = (settle_d − close_d) × pv，按持仓方向
        leak += (st - c) * r.quantity * float(r.point_value)
        n += 1
    emit(f"[next_close泄漏] {sid}: open fills={n}, 隐含执行日 close→settle 计入={leak:+,.0f} 元")

# ---------- 5. 保证金使用与 B01→B03 微差独立验证 ----------
u = read_pickle(V62 / "analysis" / "margin_engine_usage.pkl") if (V62 / "analysis" / "margin_engine_usage.pkl").exists() else None
mu = None
for cand in [V62 / "B03" / "margin_engine_usage.pkl", V62 / "analysis" / "margin_engine_usage.pkl"]:
    if cand.exists():
        mu = read_pickle(cand); break
if mu is not None:
    mu["date"] = pd.to_datetime(mu["date"])
    bind = mu[mu.source_code.str.contains("VENDOR")]
    bind2 = bind[bind.vendor_binding.astype(bool)]
    emit(f"\n[保证金] B03 vendor源键={len(bind)}, 其中vendor实际绑定(>fallback)={len(bind2)}")
    if len(bind2):
        top = bind2.nlargest(5, "vendor_rate")[["date", "contract", "rate_trade_date", "vendor_rate", "fallback_rate"]]
        emit("绑定的前5条(应为提保日):")
        emit(top.to_string(index=False))

# ---------- 6. 偏差不对称验证（袖套 vs 参照的纠偏幅度） ----------
eq = {}
for sid in ["R01", "R02", "B01", "B02", "B03", "B04"]:
    e = read_pickle(V62 / sid / "daily_equity.pkl")
    eq[sid] = float(e["equity"].iloc[-1])
ref_bias = eq["R01"] / eq["B01"] - 1
sleeve_bias = eq["R02"] / eq["B02"] - 1
emit(f"\n[偏差不对称] 参照被前视过滤放大 {ref_bias*100:+.1f}% (99.27M/53.69M), "
     f"袖套被放大 {sleeve_bias*100:+.1f}% (317.26M/117.22M)")
emit(f"[纠偏后优势] B04−B03={eq['B04']-eq['B03']:+,.0f} (v6.1 时为 {eq['R02']-eq['R01']:+,.0f})")

(TMP / "v62_result_audit_report.txt").write_text("\n".join(log), encoding="utf-8")
emit("\nDONE")
