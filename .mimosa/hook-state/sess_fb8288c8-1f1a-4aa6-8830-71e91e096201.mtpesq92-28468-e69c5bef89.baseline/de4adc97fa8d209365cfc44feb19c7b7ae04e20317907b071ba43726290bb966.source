# -*- coding: utf-8 -*-
"""T4 独立复现包（纯 numpy/纯 Python 风格；锁板 12/7/4 用与 T2b 不同的实现交叉比对）。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl），
这些文件已全部纳入 verify_20260903/pre_manifest.txt 的 SHA-256 快照，属受复核的
既有内容而非外部不可信输入；复核必须读取其内容，故使用 pandas 的受控加载接口。
不执行任何数据文件内嵌逻辑之外的可执行内容。
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仅用于仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

INITIAL = 10_000_000.0

# ---------- 1. 会计恒等式 ----------
acct_rows = []
for label, p in [("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/daily_equity.pkl"),
                 ("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/daily_equity.pkl")]:
    eq = read_pickle(p).sort_values("date").reset_index(drop=True)
    e = eq["equity"].to_numpy(dtype=float)
    net = eq["net_pnl"].to_numpy(dtype=float)
    gross = eq["gross_pnl"].to_numpy(dtype=float)
    fees = eq["fees"].to_numpy(dtype=float)
    prev = np.concatenate([[INITIAL], e[:-1]])
    r1 = float(np.max(np.abs(e - prev - net)))
    r2 = float(np.max(np.abs(net - (gross - fees))))
    r3 = float(abs(net.sum() - (e[-1] - INITIAL)))
    r4 = float(abs(e[0] - INITIAL - net[0]))
    acct_rows.append({"run": label, "equity_step_resid": r1, "net_eq_gross_minus_fees_resid": r2,
                      "cum_net_eq_terminal_resid": r3, "first_day_resid": r4,
                      "ending_equity": e[-1], "dates": len(eq)})
    emit(f"[会计] {label}: 逐日残差={r1:.10f}, 净=毛-费残差={r2:.10f}, 期末恒等残差={r3:.10f}, "
         f"首日残差={r4:.10f}, 期末权益={e[-1]:,.2f}")
pd.DataFrame(acct_rows).to_csv(TMP / "recompute_accounting.csv", index=False, encoding="utf-8-sig")

# ---------- 2. 平今=0 ----------
tt_rows = []
for label, p in [("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl"),
                 ("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")]:
    f = read_pickle(p)
    vc = f["transaction_type"].value_counts().to_dict()
    tt_rows.append({"run": label, "n_fills": len(f), **vc})
    emit(f"[平今] {label}: transaction_type 计数={vc}")
pd.DataFrame(tt_rows).to_csv(TMP / "recompute_transaction_types.csv", index=False, encoding="utf-8-sig")

# ---------- 3. 覆盖：主合约逐日有 bar（vol>0 且 close 非空） ----------
daily = read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])
bar_index = {}
for r in daily.itertuples(index=False):
    bar_index[(r.trade_date, r.ts_code)] = (r.vol, r.close)
missing_days = []
for r in mapping.itertuples(index=False):
    bar = bar_index.get((r.date, r.contract))
    if bar is None or not (bar[0] and bar[0] > 0 and pd.notna(bar[1])):
        missing_days.append((r.instrument, str(r.date.date()), r.contract))
emit(f"[覆盖] mapping 逐日主合约缺bar/零量/无收盘: {len(missing_days)} / {len(mapping)}")
if missing_days[:10]:
    emit("  示例: " + "; ".join(map(str, missing_days[:10])))
pd.DataFrame(missing_days, columns=["instrument", "date", "contract"]).to_csv(
    TMP / "recompute_mapping_missing_bars.csv", index=False, encoding="utf-8-sig")

# ---------- 4. 退市在库 ----------
basic = read_pickle(ROOT / "data/raw/tushare/fut_basic.pkl")
n_basic = basic["ts_code"].nunique()
n_daily = daily["ts_code"].nunique()
delist = pd.to_datetime(basic["delist_date"], errors="coerce")
n_delisted = int((delist < pd.Timestamp("2026-09-01")).sum())
delisted_set = set(basic.loc[delist < pd.Timestamp("2026-09-01"), "ts_code"])
n_delisted_in_daily = len(delisted_set & set(daily["ts_code"]))
emit(f"[退市] fut_basic distinct ts_code={n_basic}, fut_daily distinct={n_daily}, "
     f"basic中已退市={n_delisted}, 退市且在daily中={n_delisted_in_daily}")

# ---------- 5. v1 拼接失败 ----------
diag = json.loads((ROOT / "data/normalized/diagnostics.json").read_text(encoding="utf-8"))
failures = diag["panama"]["stitch_failures"]
emit(f"\n[v1拼接] len(stitch_failures)={len(failures)}, roll_count={diag['panama']['roll_count']}")
price_days = {}
for r in daily.itertuples(index=False):
    if pd.notna(r.close) and r.close > 0:
        price_days.setdefault(r.ts_code, set()).add(r.trade_date)
checked = []
rng = np.random.default_rng(20260903)
idx = rng.choice(len(failures), size=min(5, len(failures)), replace=False)
for i in idx:
    fitem = failures[int(i)]
    d = pd.Timestamp(fitem["date"])
    cand = list(pd.bdate_range(end=d, periods=10))[::-1]
    overlap = [dt for dt in cand if dt in price_days.get(fitem["old_contract"], set())
               and dt in price_days.get(fitem["new_contract"], set())]
    checked.append({"date": fitem["date"], "old": fitem["old_contract"], "new": fitem["new_contract"],
                    "my_overlap_days_found": len(overlap)})
    emit(f"  抽样: {fitem['date']} {fitem['old_contract']}->{fitem['new_contract']} "
         f"重叠日检索(切换日前10个工作日)={len(overlap)} （0=与'无重叠'判定一致）")
pd.DataFrame(checked).to_csv(TMP / "recompute_stitch_failures_sample.csv", index=False, encoding="utf-8-sig")

# ---------- 6. 锁板 12/7/4 交叉实现（dict 遍历，与 T2b 的 join 实现不同） ----------
lock_dir = {}
for r in daily.itertuples(index=False):
    if pd.notna(r.high) and pd.notna(r.low) and r.high == r.low and (r.vol and r.vol > 0):
        mark = r.settle if pd.notna(r.settle) else r.close
        direction = np.sign(mark - r.pre_settle) if pd.notna(r.pre_settle) else 0.0
        lock_dir[(r.trade_date, r.ts_code)] = direction
mapped_locked = [1 for r in mapping.itertuples(index=False) if (r.date, r.contract) in lock_dir]
emit(f"\n[锁板交叉-实现B] 主力映射锁板日={len(mapped_locked)}")

f_v3 = read_pickle(ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl")
f_s1 = read_pickle(ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")
seg_total = seg_adverse = 0
events = {}
for run_name, f in [("v3", f_v3), ("S1", f_s1)]:
    f = f.copy()
    f["date"] = pd.to_datetime(f["date"])
    for r in f.itertuples(index=False):
        key = (r.date, r.contract)
        if key in lock_dir:
            direction = lock_dir[key]
            adverse = (r.quantity > 0 and direction > 0) or (r.quantity < 0 and direction < 0)
            seg_total += 1
            seg_adverse += int(adverse)
            ev_key = (run_name, r.date, r.contract, int(np.sign(r.quantity)))
            events[ev_key] = events.get(ev_key, False) or adverse
ev_adverse = sum(1 for v in events.values() if v)
emit(f"[锁板交叉-实现B] 成交分段={seg_total}, 逆停板方向分段={seg_adverse}; "
     f"订单事件={len(events)}, 逆停板事件={ev_adverse}")
pd.DataFrame([{"metric": ["mapped_locked_days", "locked_fill_segments", "adverse_fill_segments",
                          "order_events", "adverse_order_events"],
               "value": [len(mapped_locked), seg_total, seg_adverse, len(events), ev_adverse]}]).to_csv(
    TMP / "recompute_locked_crosscheck.csv", index=False, encoding="utf-8-sig")

(REPORTS / "T4_offline_bundle.md").write_text(
    "# T4 独立复现包（会计/平今/覆盖/退市/拼接/锁板交叉）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT4 DONE")
