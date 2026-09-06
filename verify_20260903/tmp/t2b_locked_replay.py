# -*- coding: utf-8 -*-
"""T2b 锁板日重建与成交重放（独立实现）。
锁板日 := high==low 且 vol>0（主力映射合约口径）；方向 := sign(settle - pre_settle)。
"""
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(r"D:\FiveSectorMomentum")
TMP = ROOT / "verify_20260903" / "tmp"
REPORTS = ROOT / "verify_20260903" / "reports"

log = []
def emit(s=""):
    print(s); log.append(str(s))

daily = pd.read_pickle(ROOT / "data/raw/tushare/fut_daily.pkl")
daily["trade_date"] = pd.to_datetime(daily["trade_date"])
mapping = pd.read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])

# 主力映射行 → 当日 bar
keys = daily.set_index(["trade_date", "ts_code"])[["open", "high", "low", "close", "settle", "pre_settle", "vol"]]
mapped = mapping.join(keys, on=["date", "contract"])
n_missing = int(mapped["high"].isna().sum())
emit(f"mapped rows={len(mapped)}, 当日无bar={n_missing}")

valid = mapped.dropna(subset=["high", "low", "vol"]).copy()
valid["vol"] = valid["vol"].fillna(0)
locked = valid[valid["high"].eq(valid["low"]) & valid["vol"].gt(0)].copy()
locked["direction"] = np.sign(locked["settle"].fillna(locked["close"]) - locked["pre_settle"])
locked = locked.sort_values(["date", "instrument"])
locked[["date", "instrument", "contract", "open", "high", "low", "close", "settle", "pre_settle", "vol", "direction", "source"]].to_csv(
    TMP / "locked_board_days.csv", index=False, encoding="utf-8-sig")
emit(f"锁板日（主力映射口径，high==low 且 vol>0）: {len(locked)} 天")
emit(locked[["date", "contract", "pre_settle", "settle", "open", "vol", "direction"]].to_string(index=False))

# 成交重放
replay_rows = []
for label, p in [("v3_formal_baseline", ROOT / "outputs/v3_20260902_001129/00_formal__formal_baseline/fills.pkl"),
                 ("v4_2_S1", ROOT / "outputs/v4_2_20260903_091241/S1__strategy_sleeve_20skip5_250_equal_risk/fills.pkl")]:
    fills = pd.read_pickle(p)
    fills["date"] = pd.to_datetime(fills["date"])
    hit = fills.merge(locked[["date", "contract", "open", "pre_settle", "settle", "direction"]],
                      on=["date", "contract"], how="inner", suffixes=("", "_lock"))
    emit(f"\n{label}: fills={len(fills)}, 锁板日成交={len(hit)}")
    # 按合约-日合并同一订单的多段（v3 有分段），逐段列方向
    for r in hit.itertuples(index=False):
        side = "买入" if r.quantity > 0 else "卖出"
        board = "跌停" if r.direction < 0 else ("涨停" if r.direction > 0 else "平")
        adverse = (r.quantity > 0 and r.direction > 0) or (r.quantity < 0 and r.direction < 0)  # 逆停板方向=与停板同侧（排队劣势）
        replay_rows.append({
            "run": label, "date": str(r.date.date()), "contract": r.contract, "quantity": r.quantity,
            "side": side, "board": board, "fill_price": r.price, "open_price": r.open_price if hasattr(r, "open_price") else r.open,
            "pre_settle": r.pre_settle, "settle": r.settle, "adverse_to_board": bool(adverse),
            "easy_side": not adverse,
        })
replay = pd.DataFrame(replay_rows)
replay.to_csv(TMP / "locked_fill_replay.csv", index=False, encoding="utf-8-sig")
emit("\n=== 锁板日成交重放 ===")
emit(replay.to_string(index=False))
n_all = len(replay); n_adv = int(replay["adverse_to_board"].sum())
emit(f"\n合计: 锁板日成交 {n_all} 笔（未去重同一订单分段），逆停板方向 {n_adv} 笔")
# 去重口径（同一 run 同日同合约同方向合为一"订单事件"）
if n_all:
    ev = replay.assign(sign=np.sign(replay.quantity)).drop_duplicates(["run", "date", "contract", "sign"])
    emit(f"订单事件口径: {len(ev)} 个, 其中逆停板方向 {int(ev['adverse_to_board'].sum())} 个")

(REPORTS / "T2b_locked_replay.md").write_text(
    "# T2b 锁板方向重建与成交重放（独立实现）\n\n```\n" + "\n".join(log) + "\n```\n", encoding="utf-8")
emit("\nT2b DONE")
