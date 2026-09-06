# -*- coding: utf-8 -*-
"""费用/成交结构独立分析 + 会计勾稽独立复算（只读仓库；输出到 audit_20260903_v2/tmp/）。

信任边界：仅反序列化仓库自身产出的 .pkl/.csv 数据文件（见 pre_audit_manifest 哈希快照）。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "audit_20260903_v2" / "tmp"

lines = []
def emit(s=""):
    print(s); lines.append(str(s))

# ---------- 1. 费用规则的时间覆盖：每个品种最早精确规则 vs 最早成交日 ----------
rules = read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
insts = ["RB","T","AL","SC","RU","SP","FG","MA","UR","C","M","P","JD","LH","CF","SR","AP"]
emit("=== earliest exact rule effective_from per instrument (open) ===")
for inst in insts:
    ex = rules[(rules.instrument.eq(inst)) & (rules.contract.ne("*")) & (rules.trade_type.eq("open"))]
    if ex.empty:
        emit(f"{inst}: NO exact rules at all"); continue
    lo = pd.Timestamp(ex.effective_from.min()); hi = pd.Timestamp(ex.effective_to.max())
    emit(f"{inst}: exact rules span {lo.date()} .. {hi.date()}")

# ---------- 2. 实际成交的费用结构（v3 正式基准 与 v4_2 S1）----------
def fill_stats(label, fills_path, positions_path=None):
    f = read_pickle(Path(str(fills_path) + ".pkl") if not str(fills_path).endswith(".pkl") else Path(fills_path))
    f["date"] = pd.to_datetime(f["date"])
    emit(f"\n=== {label}: fills={len(f)}, lots={f.quantity.abs().sum():.0f} ===")
    total_comm = f.commission.sum(); total_exch = f.exchange_commission.sum(); total_slip = f.slippage_cost.sum()
    emit(f"commission(client)={total_comm:,.0f}  exchange={total_exch:,.0f}  x1.5 check={total_exch*1.5:,.0f}  slippage={total_slip:,.0f}")
    by_type = f.groupby("transaction_type").agg(segments=("quantity","size"), lots=("quantity", lambda x: x.abs().sum()),
                                                exch=("exchange_commission","sum"), client=("commission","sum"))
    emit(by_type.to_string())
    proxy = f[f.fee_is_proxy.astype(bool)] if "fee_is_proxy" in f else pd.DataFrame()
    emit(f"proxy fee segments: {len(proxy)} of {len(f)} ({len(proxy)/max(len(f),1)*100:.1f}%), proxy client fee={proxy.commission.sum() if len(proxy) else 0:,.0f} ({(proxy.commission.sum()/max(total_comm,1))*100:.1f}% of total)")
    if len(proxy):
        emit(proxy.groupby("instrument").agg(segments=("quantity","size"), client=("commission","sum")).to_string())
    by_inst = f.groupby("instrument").agg(lots=("quantity", lambda x: x.abs().sum()),
                                          client_per_lot=("commission", "sum"))
    by_inst["client_per_lot"] = by_inst["client_per_lot"] / by_inst["lots"]
    ct = f[f.transaction_type.eq("close_today")].groupby("instrument").size().rename("close_today_segments")
    by_inst = by_inst.join(ct).fillna({"close_today_segments": 0})
    emit("\nper-instrument client fee per lot / close_today segments:")
    emit(by_inst.to_string())
    # 下单日 vs 成交日执行滞后核查
    lag = (f.date - pd.to_datetime(f.created_date)).dt.days
    emit(f"execution lag days: min={lag.min()}, max={lag.max()}, share>0={(lag>0).mean()*100:.2f}%")
    f.to_csv(OUT / f"fills_{label.replace(' ','_')}.csv", index=False, encoding="utf-8-sig")
    return f

f_v3 = fill_stats("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills")
f_s1 = fill_stats("v4_2_S1_sleeve", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills")

# ---------- 3. 锁板日是否有成交 ----------
locked = pd.read_csv(OUT / "mapped_locked_board_days.csv") if (OUT / "mapped_locked_board_days.csv").exists() else None
if locked is not None and len(locked):
    locked["date"] = pd.to_datetime(locked["date"])
    emit("\n=== locked-board mapped days ===")
    emit(locked.to_string(index=False))
    for label, f in [("v3", f_v3), ("S1", f_s1)]:
        hit = f[f.set_index(["date","contract"]).index.isin(pd.MultiIndex.from_frame(locked[["date","contract"]]))]
        emit(f"{label} fills on locked days: {len(hit)}")

# ---------- 4. 会计勾稽独立复算（v4_2 S1 + v3 baseline）----------
def recompute(label, root_dir):
    root_dir = Path(root_dir)
    eq = read_pickle(root_dir / "daily_equity.pkl")
    pos = read_pickle(root_dir / "positions.pkl")
    fills = read_pickle(root_dir / "fills.pkl")
    pnl = read_pickle(root_dir / "pnl_by_instrument.pkl")
    eq = eq.sort_values("date").reset_index(drop=True)
    eq["date"] = pd.to_datetime(eq["date"])
    pos["date"] = pd.to_datetime(pos["date"]); pnl["date"] = pd.to_datetime(pnl["date"])
    fills["date"] = pd.to_datetime(fills["date"])

    # 检查1: 逐日权益 = 昨权益 + 净盈亏（净盈亏已扣费）
    prev = eq.equity.shift(1).fillna(10_000_000.0)
    r1 = (eq.equity - prev - eq.net_pnl).abs().max()
    # 检查2: gross - fees = net
    r2 = (eq.gross_pnl - eq.fees - eq.net_pnl).abs().max()
    # 检查3: fills手续费合计 = equity fees 合计
    r3 = abs(fills.commission.sum() - eq.fees.sum())
    # 检查4: 逐合约净盈亏合计 = 账户净盈亏
    r4 = abs(pnl.net_pnl.sum() - eq.net_pnl.sum())
    # 检查5: 期末权益
    r5 = abs(eq.net_pnl.sum() - (eq.equity.iloc[-1] - 10_000_000.0))
    # 检查6（独立路径）：用 bars+fills 逐合约复算逐日盈亏
    bars = read_pickle(ROOT / "data/normalized_v2/bars.pkl")
    bars["date"] = pd.to_datetime(bars["date"])
    marks = bars.set_index(["date","ts_code"])[["settlement","close","point_value"]]
    fill_groups = {d: g for d, g in fills.groupby("date")}
    pos_groups = {d: dict(zip(g.contract, g.position)) for d, g in pos.groupby("date")}
    pnl_index = pnl.set_index(["date","contract"]).net_pnl
    worst = 0.0; worst_key = None; day_max_err = 0.0
    prev_pos = {}
    prev_mark = {}
    for day in eq.date:
        day_fills = fill_groups.get(day, pd.DataFrame())
        contracts = set(prev_pos) | (set(day_fills.contract) if len(day_fills) else set())
        gross = 0.0; fees = 0.0
        for c in sorted(contracts):
            try:
                bar = marks.loc[(day, c)]
            except KeyError:
                continue
            mark = float(bar.settlement) if pd.notna(bar.settlement) and bar.settlement > 0 else float(bar.close)
            pv = float(bar.point_value)
            p = prev_pos.get(c, 0)
            v = p * (mark - prev_mark.get(c, mark)) * pv
            sub = day_fills[day_fills.contract.eq(c)] if len(day_fills) else None
            cost = 0.0
            if sub is not None and len(sub):
                v += float((sub.quantity * (mark - sub.price) * pv).sum()); cost = float(sub.commission.sum())
            gross += v; fees += cost
            recorded = pnl_index.get((day, c), 0.0)
            err = abs((v - cost) - recorded)
            if err > worst:
                worst, worst_key = err, (day, c)
        day_err = abs((gross - fees) - float(eq.loc[eq.date.eq(day), "net_pnl"].iloc[0]))
        day_max_err = max(day_max_err, day_err)
        g = pos_groups.get(day, {})
        prev_pos = g
        for c in g:
            try:
                bar = marks.loc[(day, c)]
                m = float(bar.settlement) if pd.notna(bar.settlement) and bar.settlement > 0 else float(bar.close)
                prev_mark[c] = m
            except KeyError:
                pass
    emit(f"\n=== independent accounting recompute: {label} ===")
    emit(f"daily equity identity max err: {r1:.6f}")
    emit(f"gross-fees=net max err: {r2:.6f}")
    emit(f"fills commission vs equity fees: {r3:.6f}")
    emit(f"instrument pnl vs account pnl: {r4:.6f}")
    emit(f"terminal equity identity: {r5:.6f}")
    emit(f"[independent path] worst contract-day net_pnl err: {worst:.6f} at {worst_key}")
    emit(f"[independent path] worst day net_pnl err: {day_max_err:.6f}")

recompute("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline")
recompute("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk")

# ---------- 5. v1/v2 手续费兜底实际影响（v2 场景）----------
v2_dir = ROOT / "outputs/v2_20260901_213543/vol_0p275__cancel_recalculate__slip_2p0t"
if v2_dir.exists():
    f2 = read_pickle(v2_dir / "fills.pkl")
    f2["notional_per_lot"] = f2.price * f2.point_value
    f2["fallback_fee"] = np.maximum(5.0, f2.notional_per_lot * 0.0002)
    by_inst2 = f2.groupby("instrument").agg(lots=("quantity", lambda x: x.abs().sum()),
                                            commission=("commission","sum"),
                                            avg_notional=("notional_per_lot","mean"),
                                            avg_fallback=("fallback_fee","mean"))
    by_inst2["per_lot"] = by_inst2.commission / by_inst2.lots
    emit("\n=== v2 fallback fee per lot (exchange-actual comparison baseline) ===")
    emit(by_inst2.to_string())

(OUT / "fee_fill_accounting_report.txt").write_text("\n".join(lines), encoding="utf-8")
emit("\nDONE")
