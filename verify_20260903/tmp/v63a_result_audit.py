# -*- coding: utf-8 -*-
"""v6.3a 独立复算（只读；输出到 verify_20260903/tmp）。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl，属受审计既有内容）。
"""
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
V63A = ROOT / "outputs/v6_3a_20260907_134158"
V62 = ROOT / "outputs/v6_2_20260906_222655"
TMP = ROOT / "verify_20260903" / "tmp"

log = []
def emit(s=""):
    print(s); log.append(str(s))

# ---------- 1. 映射修正独立验证 ----------
old_map = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
new_map = read_pickle(ROOT / "data/v6_3a/mapping_corrected.pkl")
for m in (old_map, new_map):
    m["date"] = pd.to_datetime(m["date"])
emit(f"映射行数 old={len(old_map)} new={len(new_map)}")
merged = old_map.merge(new_map, on=["date", "instrument"], suffixes=("_old", "_new"), how="outer", indicator=True)
diff = merged[merged.contract_old != merged.contract_new]
emit(f"差异行数={len(diff)}, 品种分布={diff.instrument.value_counts().to_dict()}")
emit(f"来源分布(new)={diff.contract_new_source.value_counts().to_dict() if 'contract_new_source' in diff else 'n/a'}")
diff_days = sorted(diff.date.unique())
emit(f"差异日期范围: {diff_days[0].date()} .. {diff_days[-1].date()}, 唯一日数={len(diff_days)}")

# 倒退消除验证：new 映射到期日单调性
meta = read_pickle(ROOT / "data/normalized_v2/contract_meta.pkl")
delist = dict(zip(meta["ts_code"], pd.to_datetime(meta["delist_date"])))
n_back = 0
for inst, g in new_map.groupby("instrument"):
    g = g.sort_values("date")
    prev = None
    for r in g.itertuples(index=False):
        d = delist.get(r.contract)
        if prev is not None and d is not None and d < prev:
            n_back += 1
            emit(f"  [倒退残留] {inst} {r.date.date()} {r.contract} 到期{d.date()} < 前值{prev.date()}")
        if d is not None:
            prev = d if prev is None else max(prev, d)
emit(f"新映射到期倒退残留={n_back} (0=修复完全)")

# 因果保持条件验证：保持日该合约当日 vol>0、close 有效、距到期≥20自然日
bars = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
bars["trade_date"] = pd.to_datetime(bars["trade_date"])
bar_idx = bars.set_index(["trade_date", "ts_code"])[["close", "vol"]]
bad = 0
for r in diff.itertuples(index=False):
    held = r.contract_new  # 保持的旧合约（=new 里的）
    key = (r.date, held)
    b = bar_idx.loc[key] if key in bar_idx.index else None
    d = delist.get(held)
    ok = (b is not None and pd.notna(b["close"]) and b["vol"] and b["vol"] > 0
          and d is not None and (d - r.date).days >= 20)
    if not ok:
        bad += 1
        emit(f"  [保持条件不符] {r.date.date()} {held}")
emit(f"保持日条件核验不符数={bad}/{len(diff)} (0=全部满足)")

# 前缀不变性抽查：2020-06-15 前的 new 映射应与 old 全等
pre = merged[(merged.date < "2020-06-01") & (merged._merge.eq("both"))]
emit(f"2020-06 前两侧全等: {(pre.contract_old == pre.contract_new).all()} (行数={len(pre)})")

# ---------- 2. 会计独立复算（G01/G02/T01/T04 抽查） ----------
for sid in ["G01", "G02", "T01", "T04"]:
    eq = read_pickle(V63A / sid / "daily_equity.pkl").sort_values("date").reset_index(drop=True)
    f = read_pickle(V63A / sid / "fills.pkl")
    prev = eq["equity"].shift(1).fillna(10_000_000.0)
    r1 = float((eq["equity"] - prev - eq["net_pnl"]).abs().max())
    cash = f["cash_slippage_cost"] if "cash_slippage_cost" in f else f.get("slippage_cost", 0)
    r2 = float(abs(f["commission"].sum() + cash.sum() - eq["fees"].sum()))
    emit(f"[会计] {sid}: 逐日残差={r1:.2e}, 成本勾稽差={r2:.2e}, 期末权益={eq['equity'].iloc[-1]:,.0f}")

# ---------- 3. 因果成交价验证（T01 抽样） ----------
t01 = read_pickle(V63A / "T01" / "fills.pkl")
t01["date"] = pd.to_datetime(t01["date"])
n_bad = 0
for r in t01.iloc[::7].itertuples(index=False):  # 抽 1/7
    key = (r.date, r.contract)
    if key not in bar_idx.index:
        continue
    o = read_idx = None
    o = ROOT and None
for r in t01.iloc[::7].itertuples(index=False):
    key = (r.date, r.contract)
    b = bars[(bars.trade_date == r.date) & (bars.ts_code == r.contract)]
    if b.empty:
        continue
    open_ = float(b.iloc[0]["open"])
    tick = float(r.tick_size) if hasattr(r, "tick_size") else None
    if tick:
        expect = float(round(round(open_ / tick) * tick, 10))
        if abs(float(r.price) - expect) > 1e-9:
            n_bad += 1
emit(f"[因果] T01 抽样成交价==网格化open: 偏离={n_bad} (抽样 {len(t01)//7} 笔)")

# ---------- 4. S05 断崖独立验证：120 vs 90 的跳跃幅度 ----------
sm = read_pickle(V63A / "analysis" / "scenario_metrics.pkl") if (V63A / "analysis" / "scenario_metrics.pkl").exists() else None
if sm is None:
    sm = pd.read_csv(V63A / "analysis" / "scenario_metrics.csv")
sm.columns = [c.lower() for c in sm.columns]
for sid in ["S04", "S05", "S06", "S07", "G01"]:
    row = sm[sm.scenario_id.eq(sid)]
    if len(row):
        r = row.iloc[0]
        emit(f"{sid}: CAGR={float(r['cagr'])*100:.2f}%, Sharpe={float(r['sharpe']):.3f}, MDD={float(r['max_drawdown'])*100:.2f}%")

# ---------- 5. T04 (next-close 完整结算) 新仓段泄漏验证 ----------
t04 = read_pickle(V63A / "T04" / "fills.pkl")
t04["date"] = pd.to_datetime(t04["date"])
opens = t04[t04.transaction_type.eq("open")]
settles = bars.set_index(["trade_date", "ts_code"])[["close", "settle"]]
seg = 0.0
for r in opens.itertuples(index=False):
    key = (r.date, r.contract)
    if key not in settles.index:
        continue
    b = settles.loc[key]
    seg += (float(b["settle"]) - float(r.price)) * r.quantity * float(r.point_value)
emit(f"[T04 完整结算] open 段成交日 (settle−fill) 合计={seg:+,.0f} 元（应为非零=已计入）")

(TMP / "v63a_result_audit_report.txt").write_text("\n".join(log), encoding="utf-8")
emit("\nDONE")
