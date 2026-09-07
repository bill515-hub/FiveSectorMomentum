# -*- coding: utf-8 -*-
"""全版本成交时点核查：成交日 vs 订单创建日（信号日）的滞后，及成交参考价字段。

信任边界：仅反序列化 D:/FiveSectorMomentum 仓库自身产出的数据文件（.pkl，属受审计既有内容）。
"""
from pathlib import Path

import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件（见上信任边界）

ROOT = Path(r"D:\FiveSectorMomentum")

log = []
def emit(s=""):
    print(s); log.append(str(s))

def check(label, path, price_col=None, created_col="created_date", date_col="date"):
    try:
        f = read_pickle(path)
    except Exception as e:
        emit(f"{label}: 读取失败 {type(e).__name__}")
        return
    if f.empty or created_col not in f.columns or date_col not in f.columns:
        emit(f"{label}: 空或无列")
        return
    d = pd.to_datetime(f[date_col]); c = pd.to_datetime(f[created_col])
    lag = (d - c).dt.days
    n = len(f)
    # 判断价字段
    price_ref = None
    for cand in (["reference_field", "price_source", "exec_reference"]):
        if cand in f.columns:
            price_ref = f[cand].value_counts().to_dict()
            break
    emit(f"{label}: n={n}, lag(days): min={lag.min()}, max={lag.max()}, "
         f">0占比={(lag > 0).mean() * 100:.2f}%, ==0占比={(lag == 0).mean() * 100:.2f}%"
         + (f", 参考价字段={price_ref}" if price_ref else ""))

# 交易日历（用于把自然日 lag 捘成交易日口径校验：lag>=1 自然日且 d 是开市日）
emit("=== 各版本 fills 的成交滞后 ===")

# v1/v2 (engine.py 时代)
for tag, p in [
    ("v1(20260901_180546, vol0.275/cancel/slip2)", ROOT / "outputs/20260901_180546/vol_0p275__cancel_recalculate__slip_2p0t"),
    ("v2(213543, 同参)", ROOT / "outputs/v2_20260901_213543/vol_0p275__cancel_recalculate__slip_2p0t"),
]:
    check(tag, p / "fills.pkl")

# v3 全场景抽 3 个
for s in ["00_formal__formal_baseline", "02_slippage__normal_slippage_daily", "07_break_even_fee__break_even_fee_12p0"]:
    check(f"v3/{s}", ROOT / "outputs/v3_20260902_001129" / s / "fills.pkl")

# v4
for s in ["00_reference__reference_v3_252", "02_single_skip__single_20_skip5", "05_pressure__multi_all_raw_fixed_3tick"]:
    check(f"v4/{s}", ROOT / "outputs/v4_20260902_102628" / s / "fills.pkl")

# v4.1
for s in ["00_gate__gate_reference_v3_252", "04_corrected_sleeve__strategy_sleeve_all_equal_risk"]:
    check(f"v4.1/{s}", ROOT / "outputs/v4_1_20260902_163841" / s / "fills.pkl")

# v4.2
for s in ["G1__single_20_skip5", "S1__strategy_sleeve_20skip5_250_equal_risk", "S2__strategy_sleeve_20skip5_250_equal_risk_fixed_3tick"]:
    check(f"v4.2/{s}", ROOT / "outputs/v4_2_20260903_091241" / s / "fills.pkl")

# v6.1
for s in ["R01", "P01", "P03", "P07", "P09", "P11"]:
    check(f"v6.1/{s}", ROOT / "outputs/v6_1_20260906_155224" / s / "fills.pkl")

# v6.2
for s in ["R01", "B01", "B03", "T01"]:
    check(f"v6.2/{s}", ROOT / "outputs/v6_2_20260906_222655" / s / "fills.pkl")

# v6.3a 全部 17
for s in ["G01", "G02", "S01", "S02", "S03", "S04", "S05", "S06", "S07", "D01", "D02",
          "T01", "T02", "T03", "N01", "N02", "T04"]:
    check(f"v6.3a/{s}", ROOT / "outputs/v6_3a_20260907_134158" / s / "fills.pkl")

(Path(r"D:\FiveSectorMomentum\verify_20260903\tmp") / "fill_timing_report.txt").write_text("\n".join(log), encoding="utf-8")
emit("\nDONE")
