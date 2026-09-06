# -*- coding: utf-8 -*-
"""T5 日历换源：akshare 新浪交易日历 vs 仓库 v4_2 独立日历（tushare fut_trade_cal）。"""
from pathlib import Path

import pandas as pd
import akshare as ak

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

sina = ak.tool_trade_date_hist_sina()
emit(f"sina calendar rows={len(sina)}, columns={list(sina.columns)}")
sina_dates = pd.to_datetime(sina["trade_date"]).sort_values().unique()
sina_set = set(pd.DatetimeIndex(sina_dates).normalize())

repo = pd.read_pickle(ROOT / "outputs/v4_2_20260903_091241/calendar/calendar_daily.pkl")
repo["date"] = pd.to_datetime(repo["date"])
open_days = set(repo.loc[repo.is_open.eq(1), "date"].unique())

lo = max(min(sina_set), min(open_days)); hi = max(min(max(sina_set), max(open_days)), lo)
# 对比仅限仓库日历自身覆盖区间（避免新浪更早历史造成假差异）
sina_scope = {d for d in sina_set if lo <= d <= hi}
repo_scope = {d for d in open_days if lo <= d <= hi}
emit(f"对比区间(=仓库日历覆盖): {lo.date()} .. {max(repo_scope).date()}  (新浪日历终点 {max(sina_set).date()})")
emit(f"新浪开市日={len(sina_scope)}, 仓库日历开市日={len(repo_scope)}")

only_sina = sorted(sina_scope - repo_scope)
only_repo = sorted(repo_scope - sina_scope)
emit(f"仅新浪开市（仓库判休）: {len(only_sina)} -> {[str(d.date()) for d in only_sina[:20]]}")
emit(f"仅仓库开市（新浪判休）: {len(only_repo)} -> {[str(d.date()) for d in only_repo[:20]]}")

checks = {
    "2020-02-03": ("应开市（COVID 首个复市交易日）", True),
    "2020-01-31": ("应休市（春节延长假期）", False),
    "2020-10-01": ("应休市（国庆）", False),
    "2021-02-11": ("应休市（除夕当周休市）", False),
    "2024-02-09": ("应休市（除夕前一天/春节前最后交易日应为其前日，核验用）", None),
}
emit("\n人工锚点核对：")
for d, (note, expect) in checks.items():
    dt = pd.Timestamp(d)
    in_repo = dt in repo_scope; in_sina = dt in sina_scope
    emit(f"  {d} {note}: 仓库开市={in_repo}, 新浪开市={in_sina}" + (f" (期望开市={expect})" if expect is not None else ""))

pd.DataFrame({"only_in_sina": [str(d.date()) for d in only_sina] + [""] * max(0, len(only_repo) - len(only_sina)),
              "only_in_repo": [str(d.date()) for d in only_repo] + [""] * max(0, len(only_sina) - len(only_repo))}
             ).to_csv(TMP / "calendar_diff.csv", index=False, encoding="utf-8-sig")

(REPORTS / "T5_calendar_cross_source.md").write_text(
    "# T5 日历换源（akshare 新浪 vs 仓库 tushare 日历）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT5 DONE")
