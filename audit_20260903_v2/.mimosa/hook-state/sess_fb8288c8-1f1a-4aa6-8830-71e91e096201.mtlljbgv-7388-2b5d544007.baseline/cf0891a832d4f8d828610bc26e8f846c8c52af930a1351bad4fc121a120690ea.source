# -*- coding: utf-8 -*-
"""反脆弱自检：构造反例检验核心结论 + 材料性测算（只读仓库；输出到审计tmp）。

信任边界：仅反序列化仓库自身产出的数据文件（见 pre_audit_manifest 哈希快照）。
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

def load_result(directory):
    d = Path(directory)
    return {
        "equity": read_pickle(d / "daily_equity.pkl"),
        "fills": read_pickle(d / "fills.pkl"),
        "pnl": read_pickle(d / "pnl_by_instrument.pkl"),
        "positions": read_pickle(d / "positions.pkl"),
    }

# ============ 材料性：v3 / v4_2 S1 / v4_2 G1 期末权益与净利 ============
for label, p in [
    ("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline"),
    ("v4_2_S1_sleeve", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk"),
    ("v4_2_G1_single20skip5", ROOT / "outputs/v4_2_20260903_091241/G1__single_20_skip5"),
    ("v4_2_G2_single250", ROOT / "outputs/v4_2_20260903_091241/G2__single_250"),
]:
    r = load_result(p)
    eq = r["equity"].sort_values("date")
    f = r["fills"]; f["date"] = pd.to_datetime(f["date"])
    emit(f"{label}: ending_equity={eq.equity.iloc[-1]:,.0f}  net_profit={eq.net_pnl.sum():,.0f}  "
         f"commission={f.commission.sum():,.0f}  slippage={f.slippage_cost.sum():,.0f}")

# ============ 反证1：RB/SP 费率 /10000→/1000 的成本影响 ============
emit("\n=== 反证1：若 tushare 费率字段为千分数（证据支持），改用 /1000 后的成本差 ===")
for label, p in [
    ("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline"),
    ("v4_2_S1_sleeve", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk"),
]:
    f = read_pickle(Path(p) / "fills.pkl"); f["date"] = pd.to_datetime(f["date"])
    rs = f[f.instrument.isin(["RB", "SP"])].copy()
    # 客户手续费 = exchange * fee_multiplier；rate 部分占比 = fee_rate*price*pv / fee_per_lot_total
    rate_component = (rs.fee_rate * rs.price * rs.point_value).fillna(0) * rs.quantity.abs() * rs.fee_multiplier
    perlot_component = rs.fee_per_lot.fillna(0) * rs.quantity.abs() * rs.fee_multiplier
    emit(f"{label}: RB+SP lots={rs.quantity.abs().sum():,.0f}  client fee={rs.commission.sum():,.0f}")
    emit(f"  其中费率部分(client, /10000口径)={rate_component.sum():,.0f}  每手部分={perlot_component.sum():,.0f}")
    undercharge = rate_component.sum() * 9  # /1000 与 /10000 相差 9 倍额外
    total_cost = f.commission.sum() + f.slippage_cost.sum()
    eq = read_pickle(Path(p) / "daily_equity.pkl")
    net = eq.sort_values("date").net_pnl.sum()
    emit(f"  若按千分数口径(/1000)，额外手续费={undercharge:,.0f}；"
         f"占总成本={undercharge/total_cost*100:.2f}%；占净利={undercharge/net*100:.2f}%")
    emit(f"  修正后净利={net-undercharge:,.0f}（原 {net:,.0f}）")

# ============ 反证2：锁板日成交方向核查（若为顺方向成交则无乐观偏差） ============
emit("\n=== 反证2：锁板日 6 笔 S1 成交的方向与当日涨跌方向 ===")
locked = pd.read_csv(OUT / "mapped_locked_board_days.csv")
locked["date"] = pd.to_datetime(locked["date"])
s1 = read_pickle(ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")
s1["date"] = pd.to_datetime(s1["date"])
v3 = read_pickle(ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl")
v3["date"] = pd.to_datetime(v3["date"])
bars = read_pickle(ROOT / "data/normalized_v2/bars.pkl")
bars["date"] = pd.to_datetime(bars["date"])
prev_close = bars.set_index(["date", "ts_code"])["close"].shift(0)
bars_sorted = bars.sort_values(["ts_code", "date"]).reset_index(drop=True)
bars_sorted["prev_close"] = bars_sorted.groupby("ts_code")["close"].shift(1)
pc = bars_sorted.set_index(["date", "ts_code"])["prev_close"]
for tag, fills in [("S1", s1), ("v3", v3)]:
    hit = fills.merge(locked[["date", "contract", "open"]], on=["date", "contract"], how="inner",
                      suffixes=("", "_locked"))
    for _, row in hit.iterrows():
        try:
            prev = pc.loc[(row["date"], row["contract"])]
        except KeyError:
            prev = np.nan
        direction = "买入" if row["quantity"] > 0 else "卖出"
        move = "跌停/低开" if (pd.notna(prev) and row["open"] < prev) else ("涨停/高开" if pd.notna(prev) else "?")
        # 顺方向=与价格运动同侧容易成交：跌停日买入易成交、卖出难；涨停反之
        easy = (direction == "买入" and move.startswith("跌")) or (direction == "卖出" and move.startswith("涨"))
        emit(f"{tag} {row['date'].date()} {row['contract']} {direction} {abs(row['quantity'])}手 "
             f"@open={row['open']} prev_close={prev} {move} 顺方向易成交={easy}")

# ============ 反证3：v4_1 袖套（20日快腿）是否存在平今分段 ============
emit("\n=== 反证3：v4_1 修正袖套的平今分段计数 ===")
for d in sorted((ROOT / "outputs/v4_1_20260902_163841").glob("04_corrected_sleeve__*")):
    f = read_pickle(d / "fills.pkl")
    ct = int(f.transaction_type.eq("close_today").sum()) if "transaction_type" in f else -1
    emit(f"{d.name}: fills={len(f)}, close_today_segments={ct}")

# ============ 反证4：独立日历本身可信度（年度交易日数分布） ============
emit("\n=== 反证4：独立日历每年开市日数（ sanity：中国期货≈238-248 日/年） ===")
cal = read_pickle(ROOT / "outputs/v4_2_20260903_091241/calendar/calendar_daily.pkl")
cal["date"] = pd.to_datetime(cal["date"])
per_year = cal[cal.is_open.eq(1)].groupby(cal.date.dt.year).size()
emit(per_year.to_string())
emit(f"exchanges in calendar: {sorted(cal.exchange.unique())}")

# ============ 反证5：RB 2015-2020（无精确规则的代理期）真实费率更高？ ============
emit("\n=== 反证5：RB 代理期(2015-2020)成交规模（若真实费率为万1，代理=万0.1亦低估10倍） ===")
for label, p in [("v3", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline"),
                 ("S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk")]:
    f = read_pickle(Path(p) / "fills.pkl"); f["date"] = pd.to_datetime(f["date"])
    rb = f[f.instrument.eq("RB")]
    pre = rb[rb.date < "2021-01-04"]
    proxy_mask = pre.fee_source_type.astype(str).str.contains("proxy")
    emit(f"{label}: RB总手数={rb.quantity.abs().sum():,.0f}, 2015-2020手数={pre.quantity.abs().sum():,.0f}, "
         f"其中代理规则手数={pre[proxy_mask].quantity.abs().sum():,.0f}")
    # 若2015-2020真实费率为万1（2016-2018甚至更高：开万1/平今万3），按万1重估
    if len(pre):
        notional = (pre.price * pre.point_value * pre.quantity.abs()).sum()
        real_fee = notional * 1e-4 * 1.5
        emit(f"  代理期名义成交额={notional/1e8:.2f}亿；按万1×1.5客户倍数重估手续费={real_fee:,.0f} "
             f"vs 记录值={pre.commission.sum():,.0f}")

(OUT / "refutation_materiality_report.txt").write_text("\n".join(lines), encoding="utf-8")
emit("\nDONE")
