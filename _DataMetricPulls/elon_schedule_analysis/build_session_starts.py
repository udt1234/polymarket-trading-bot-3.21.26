"""Build per-session start/end table from clean X-API parquet.
Session = active posting block segmented by >=5h sleep/away gap.
Output: session_starts.csv (one row per session, >=3 tweets).
"""
import pandas as pd, numpy as np
from pathlib import Path

SRC = Path('_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet')
OUT = Path('_DataMetricPulls/elon_schedule_analysis/session_starts.csv')

df = pd.read_parquet(SRC)
df['et'] = pd.to_datetime(df['ts_utc'], utc=True, format='ISO8601').dt.tz_convert('America/New_York')
df = df.sort_values('et').reset_index(drop=True)
gap = df['et'].diff().dt.total_seconds()/3600
df['sess'] = (gap.isna() | (gap >= 5)).cumsum()

s = df.groupby('sess').agg(n=('et','size'), start=('et','min'), end=('et','max')).reset_index()
s = s[s['n'] >= 3].copy()
s['start_hr'] = s['start'].dt.hour
s['start_min'] = s['start'].dt.hour + s['start'].dt.minute/60
s['dur_h'] = (s['end']-s['start']).dt.total_seconds()/3600
s['end_abs'] = s['start_min'] + s['dur_h']         # >24 => past midnight
# the ET calendar date of the morning the session started (its "day")
s['day'] = s['start'].dt.date
# noon-anchored auction date + that day's counted-tweet volume
df['adate'] = (df['et']-pd.Timedelta(hours=12)).dt.date
vol = df[df['counts_main_feed']==True].groupby('adate').size().rename('mf_count')
s['adate'] = (s['start']-pd.Timedelta(hours=12)).dt.date
s = s.merge(vol, on='adate', how='left')
s[['day','start','end','n','start_hr','start_min','dur_h','end_abs','mf_count']].to_csv(OUT, index=False)
print('wrote', OUT, 'rows', len(s))
print(s['start_hr'].value_counts().sort_index())
