# -*- coding: utf-8 -*-
"""独立数据质量分析（只读仓库数据；全部输出写入 audit_20260903_v2/tmp/）。

信任边界说明：本脚本仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件
（bars/mapping/adjusted_prices/fee rules 等 .pkl），这些文件已全部纳入
audit_20260903_v2/pre_audit_manifest.txt 的 SHA-256 快照，属受审计的既有内容，
非外部不可信输入；审计必须读取其内容，故使用 pandas 反序列化接口。
配置解析一律使用 yaml.safe_load。不执行 pickle 中任何代码路径之外的逻辑。
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pandas import read_pickle  # 仅用于仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")
OUT = ROOT / "audit_20260903_v2" / "tmp"
OUT.mkdir(parents=True, exist_ok=True)

report_lines = []
def emit(line=""):
    print(line)
    report_lines.append(str(line))

# ---------- 0. bars 结构与涨跌停/结算列缺失确认 ----------
bars_v2 = read_pickle(ROOT / "data/normalized_v2/bars.pkl")
emit("=== bars_v2 columns ===")
emit(list(bars_v2.columns))
emit(f"bars rows={len(bars_v2)}, contracts={bars_v2.ts_code.nunique()}, instruments={sorted(bars_v2.instrument.unique())}")
emit(f"date range: {bars_v2.date.min()} .. {bars_v2.date.max()}")

has_limit_cols = "upper_limit" in bars_v2.columns
has_margin_cols = "long_margin_rate" in bars_v2.columns
has_fee_cols = "trading_fee" in bars_v2.columns
emit(f"upper/lower_limit columns present: {has_limit_cols}")
emit(f"long/short_margin_rate columns present: {has_margin_cols}")
emit(f"trading_fee columns present: {has_fee_cols}")
emit(f"settlement non-null ratio: {bars_v2.settlement.notna().mean():.4f}")

# ---------- 1. 独立日历核对 ----------
cal = read_pickle(ROOT / "outputs/v4_2_20260903_091241/calendar/calendar_daily.pkl")
cal["date"] = pd.to_datetime(cal["date"])
open_days = cal.loc[cal.is_open.eq(1), "date"].sort_values().reset_index(drop=True)
emit(f"\ncalendar open days: {len(open_days)} ({open_days.min().date()} .. {open_days.max().date()})")

mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])
adj = read_pickled = read_pickle(ROOT / "data/normalized_v2/adjusted_prices.pkl")
adj["date"] = pd.to_datetime(adj["date"])

START, END = pd.Timestamp("2015-01-01"), pd.Timestamp("2026-08-31")
expected = pd.DatetimeIndex(open_days[(open_days >= START) & (open_days <= END)])
emit(f"expected trading days 2015-01-01..2026-08-31 by independent calendar: {len(expected)}")

rows = []
for instrument, group in adj.groupby("instrument"):
    got = pd.DatetimeIndex(group["date"].sort_values().unique())
    first = got.min()
    exp_from_first = expected[expected >= first]
    missing = exp_from_first.difference(got)
    extra = got.difference(open_days)
    map_days = pd.DatetimeIndex(mapping.loc[mapping.instrument.eq(instrument), "date"].unique())
    mapped_missing = map_days.difference(got)
    dup = group.duplicated("date").sum()
    rows.append({
        "instrument": instrument, "first_price_day": str(first.date()), "last": str(got.max().date()),
        "calendar_days_from_first": len(exp_from_first), "price_days": len(got),
        "missing_price_days_vs_calendar": len(missing),
        "missing_days_list": ",".join(d.strftime("%Y-%m-%d") for d in missing[:40]),
        "price_on_closed_days": len(extra),
        "closed_day_list": ",".join(d.strftime("%Y-%m-%d") for d in extra[:20]),
        "mapping_days": len(map_days), "mapping_days_without_price": len(mapped_missing),
        "duplicate_price_days": int(dup),
    })
coverage = pd.DataFrame(rows)
coverage.to_csv(OUT / "coverage_by_instrument.csv", index=False, encoding="utf-8-sig")
emit("\n=== per-instrument calendar coverage ===")
emit(coverage[["instrument","first_price_day","calendar_days_from_first","price_days",
               "missing_price_days_vs_calendar","price_on_closed_days","mapping_days_without_price","duplicate_price_days"]].to_string(index=False))

# ---------- 2. 主力合约当日缺bar / 涨跌停锁板 / 零成交 ----------
bars_v2["date"] = pd.to_datetime(bars_v2["date"])
mapped = mapping.merge(
    bars_v2[["date","ts_code","high","low","open","close","volume","oi"]],
    left_on=["date","contract"], right_on=["date","ts_code"], how="left")
missing_bar = mapped[mapped["open"].isna()]
emit(f"\nmapped (date,contract) rows without any bar: {len(missing_bar)} of {len(mapped)}")
if len(missing_bar):
    miss_by_instr = missing_bar.groupby("instrument").size().sort_values(ascending=False)
    emit(miss_by_instr.to_string())
    missing_bar.assign(date=lambda x: x.date.dt.strftime("%Y-%m-%d")).to_csv(
        OUT / "mapped_days_without_bar.csv", index=False, encoding="utf-8-sig")

valid = mapped.dropna(subset=["high","low"])
locked = valid[valid["high"].eq(valid["low"])]
emit(f"mapped rows with high==low (locked board): {len(locked)} ({len(locked)/max(len(valid),1)*100:.3f}%)")
if len(locked):
    locked.assign(date=lambda x: x.date.dt.strftime("%Y-%m-%d")).to_csv(
        OUT / "mapped_locked_board_days.csv", index=False, encoding="utf-8-sig")
zero_vol = valid[valid["volume"].fillna(0).le(0)]
emit(f"mapped rows with volume<=0: {len(zero_vol)}")

# ---------- 3. 拼接失败（v1 宽universe 与 v2）----------
for sub in ["normalized", "normalized_v2"]:
    diag = json.loads((ROOT / "data" / sub / "diagnostics.json").read_text(encoding="utf-8"))
    emit(f"\n{sub} panama: roll_count={diag['panama']['roll_count']}, "
         f"stitch_failures={len(diag['panama']['stitch_failures'])}, rows={diag['panama']['rows']}")
    if diag["panama"]["stitch_failures"]:
        emit(json.dumps(diag["panama"]["stitch_failures"][:10], ensure_ascii=False))

# ---------- 4. 幸存者偏差 ----------
basics = read_pickle(ROOT / "data/raw/tushare/fut_basic.pkl")
insts = sorted(adj.instrument.unique())
emit("\n=== survivorship: fut_basic contracts per instrument (incl. delisted) ===")
surv_rows = []
for inst in insts:
    inst_contracts = basics[basics["fut_code"].astype(str).str.upper().eq(inst)]
    delisted = inst_contracts[pd.to_datetime(inst_contracts["delist_date"], errors="coerce") < pd.Timestamp("2026-09-01")]
    bars_inst = bars_v2[bars_v2.instrument.eq(inst)]
    in_bars = inst_contracts[inst_contracts["ts_code"].isin(bars_inst.ts_code.unique())]
    surv_rows.append({
        "instrument": inst, "fut_basic_contracts": len(inst_contracts),
        "delisted_before_20260901": len(delisted),
        "contracts_in_bars": len(in_bars),
        "delisted_in_bars": int(in_bars["ts_code"].isin(delisted["ts_code"]).sum()),
        "earliest_list_date": str(pd.to_datetime(inst_contracts["list_date"], errors="coerce").min().date()) if len(inst_contracts) else None,
    })
surv = pd.DataFrame(surv_rows)
surv.to_csv(OUT / "survivorship_by_instrument.csv", index=False, encoding="utf-8-sig")
emit(surv.to_string(index=False))

# ---------- 5. 配置 universe vs FALLBACK_ECONOMICS ----------
sys.path.insert(0, str(ROOT / "src"))
from five_sector_momentum.universe import FALLBACK_ECONOMICS  # noqa: E402
import yaml  # noqa: E402
missing_fb = []
for cfg in sorted((ROOT / "configs").glob("*.yaml")):
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    insts_cfg = set()
    for sector, items in raw["universe"]["absolute"].items():
        insts_cfg.update(items)
    for sector, exg in raw["universe"]["cross_sectional"].items():
        for ex, items in exg.items():
            insts_cfg.update(items)
    miss = sorted(insts_cfg - set(FALLBACK_ECONOMICS))
    if miss:
        missing_fb.append((cfg.name, miss))
emit(f"\nconfig instruments missing from FALLBACK_ECONOMICS: {missing_fb if missing_fb else 'NONE'}")

# ---------- 6. 逐品种当前费率规则摘要（v3+ 费用模型输入）----------
rules = read_pickle(ROOT / "data/v3/fees/historical_fee_rules.pkl")
recent = rules[(rules.instrument.isin(insts)) & (rules.trade_type.eq("open"))]
fee_rows = []
for inst, g in recent.groupby("instrument"):
    exact = g[g.contract.ne("*")].sort_values("effective_from")
    proxy = g[g.contract.eq("*")]
    last = exact.iloc[-1] if not exact.empty else (proxy.iloc[-1] if not proxy.empty else None)
    if last is None:
        continue
    fee_rows.append({
        "instrument": inst, "last_effective_from": str(pd.Timestamp(last.effective_from).date()),
        "fee_per_lot": float(last.fee_per_lot), "fee_rate(万分数)": float(last.fee_rate)*10000,
        "source_type": last.source_type, "is_proxy": bool(last.is_proxy),
        "n_exact_open_rules": int(len(exact)),
    })
fee_tbl = pd.DataFrame(fee_rows).sort_values("instrument")
fee_tbl.to_csv(OUT / "fee_rules_last_per_instrument.csv", index=False, encoding="utf-8-sig")
emit("\n=== latest open-fee rule per instrument (v3+ fee model) ===")
emit(fee_tbl.to_string(index=False))

cov_fee = pd.read_csv(ROOT / "data/v3/fees/tushare_fee_coverage.csv")
emit("\n=== tushare fee coverage (mapping-day basis) ===")
emit(cov_fee.to_string(index=False))
rule_cov = pd.read_csv(ROOT / "data/v3/fees/fee_rule_coverage.csv")
emit("\n=== fee rule interval coverage ===")
emit(rule_cov.to_string(index=False))

# ---------- 7. 随机抽样 (合约, 日期) 供跨源核对 ----------
sample_pool = bars_v2[bars_v2.instrument.isin(insts)].dropna(subset=["close"]).sample(40, random_state=20260903)
sample = sample_pool[["ts_code","date","open","high","low","close","settlement","volume","oi","point_value"]]
sample["date"] = sample["date"].dt.strftime("%Y%m%d")
sample.to_csv(OUT / "random_sample_for_crosscheck.csv", index=False, encoding="utf-8-sig")
emit("\nrandom 40 (contract,date) saved for cross-source check")

# ---------- 8. v1(宽universe) adjusted 价格缺口统计 ----------
adj1 = read_pickle(ROOT / "data/normalized/adjusted_prices.pkl")
adj1["date"] = pd.to_datetime(adj1["date"])
gaps = []
for inst, g in adj1.groupby("instrument"):
    got = pd.DatetimeIndex(g["date"].sort_values().unique())
    first = got.min()
    exp_from_first = expected[expected >= first]
    gaps.append({"instrument": inst, "days": len(got), "missing": len(exp_from_first.difference(got))})
g1 = pd.DataFrame(gaps)
emit("\n=== v1 wide-universe adjusted price missing days (top 15) ===")
emit(g1.sort_values("missing", ascending=False).head(15).to_string(index=False))

(OUT / "data_quality_report.txt").write_text("\n".join(report_lines), encoding="utf-8")
emit("\nDONE")
