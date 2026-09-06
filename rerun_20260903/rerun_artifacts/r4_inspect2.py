import pandas as pd, numpy as np
from pathlib import Path
ROOT = Path(r"D:\FiveSectorMomentum")
DATA = ROOT / "data" / "normalized_v2"
bars = pd.read_pickle(DATA / "bars.pkl")
cm = pd.read_pickle(DATA / "contract_meta.pkl")
mp = pd.read_pickle(DATA / "mapping.pkl")

uni = ['RB','T','AL','C','M','P','JD','LH','CF','SR','AP','FG','MA','UR','RU','SP','SC']
sub = bars[bars.instrument.isin(uni)]
print("universe bars rows:", len(sub))
print("point_value non-null:", sub.point_value.notna().sum(), "of", len(sub))
print("tick_size non-null:", sub.tick_size.notna().sum())
print("fallback_margin_rate non-null:", sub.fallback_margin_rate.notna().sum())
print(sub[['instrument','ts_code','point_value','tick_size','fallback_margin_rate']].drop_duplicates().head(40).to_string())

# check whether mapped contract has bars row each mapping day
mpu = mp[mp.instrument.isin(uni)]
m = mpu.merge(bars[['date','ts_code','close','settlement','point_value','tick_size']], left_on=['date','contract'], right_on=['date','ts_code'], how='left')
print("mapped merge missing close:", m.close.isna().sum(), "of", len(m))
print("mapped merge point_value null:", m.point_value.isna().sum())
print("mapped tick_size null:", m.tick_size.isna().sum())

# settlement vs close in bars for universe
print("settlement>0 fraction:", (sub.settlement>0).mean())

# long/short margin columns?
print([c for c in bars.columns if 'margin' in c])
print([c for c in bars.columns if 'limit' in c])
