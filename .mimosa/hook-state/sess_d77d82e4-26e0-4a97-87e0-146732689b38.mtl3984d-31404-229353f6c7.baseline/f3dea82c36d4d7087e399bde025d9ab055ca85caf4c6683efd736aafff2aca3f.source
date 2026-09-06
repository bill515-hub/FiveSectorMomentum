"""Acquire an independent calendar only; never refresh price caches."""
import os
from pathlib import Path
import sys
import json
import time
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'src'))
import pandas as pd
import tushare as ts
from five_sector_momentum.data_source import load_local_env

out = ROOT/'outputs/v4_2_20260903_091241/calendar'
out.mkdir(parents=True, exist_ok=True)
if any(out.iterdir()):
    raise FileExistsError('Calendar directory is not empty; never overwrite saved calendar data')
load_local_env(ROOT)
pro = ts.pro_api(os.environ['TUSHARE_TOKEN'])
calls=[]; frames=[]
for exchange in ['SHFE','DCE','CZCE','CFFEX','INE']:
    for start,end in [('20140101','20181231'),('20190101','20221231'),('20230101','20261231')]:
        frame = pro.fut_trade_cal(exchange=exchange,start_date=start,end_date=end)
        if frame is None or frame.empty:
            raise RuntimeError(f'Empty independent calendar: {exchange} {start}')
        frame.to_csv(out/f'raw_{exchange}_{start}.csv',index=False,encoding='utf-8-sig')
        frame.to_pickle(out/f'raw_{exchange}_{start}.pkl')
        frames.append(frame)
        calls.append({'exchange':exchange,'start':start,'end':end,'rows':len(frame),'endpoint':'fut_trade_cal','source':'https://tushare.pro/document/2?doc_id=467','retrieved_utc':pd.Timestamp.now(tz='UTC').isoformat(),'historical_announcement_timestamp_available':False})
        print(exchange,start,len(frame),flush=True)
        time.sleep(.2)
raw=pd.concat(frames,ignore_index=True)
raw['date']=pd.to_datetime(raw.cal_date)
daily=raw[['exchange','date','is_open']].sort_values(['exchange','date']).reset_index(drop=True)
assert not daily.duplicated(['exchange','date']).any()
daily.to_csv(out/'calendar_daily.csv',index=False,encoding='utf-8-sig');daily.to_pickle(out/'calendar_daily.pkl')
pd.DataFrame(calls).to_csv(out/'calendar_sources.csv',index=False,encoding='utf-8-sig');pd.DataFrame(calls).to_pickle(out/'calendar_sources.pkl')
print('Independent calendar saved; old caches untouched.',flush=True)
