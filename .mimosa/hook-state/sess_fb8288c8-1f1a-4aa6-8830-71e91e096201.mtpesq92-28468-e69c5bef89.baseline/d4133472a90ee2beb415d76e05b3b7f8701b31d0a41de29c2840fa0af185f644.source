# -*- coding: utf-8 -*-
"""主力映射语义抽查：fut_mapping 切换日 vs OI 交叉日（只读仓库；输出到审计tmp）。"""
from pathlib import Path
import pandas as pd
from pandas import read_pickle  # 仓库自身数据文件

ROOT = Path(r"D:\FiveSectorMomentum")

bars = read_pickle(ROOT / "data/normalized_v2/bars.pkl")
bars["date"] = pd.to_datetime(bars["date"])
mapping = read_pickle(ROOT / "data/normalized_v2/mapping.pkl")
mapping["date"] = pd.to_datetime(mapping["date"])

for inst in ["RB", "FG", "SC"]:
    m = mapping[mapping.instrument.eq(inst)].sort_values("date").reset_index(drop=True)
    switches = m[m.contract.ne(m.contract.shift())].iloc[1:]  # 跳过首行
    print(f"\n{inst}: mapping rows={len(m)}, switches={len(switches)}")
    # 抽前5次与最后2次切换，检查切换日新合约 OI 是否已 >= 旧合约 OI（当日信息）
    idxs = list(switches.index[:5]) + list(switches.index[-2:])
    for i in idxs:
        row = m.loc[i]
        d = row["date"]
        oi = bars[bars.date.eq(d) & bars.instrument.eq(inst)].set_index("ts_code")["oi"]
        old = m.loc[i - 1, "contract"]
        new = row["contract"]
        oi_old = float(oi.get(old, float("nan")))
        oi_new = float(oi.get(new, float("nan")))
        print(f"  {d.date()} {old} -> {new}: OI old={oi_old:,.0f} new={oi_new:,.0f} "
              f"new>=old={oi_new >= oi_old} source={row.get('source','?')}")
