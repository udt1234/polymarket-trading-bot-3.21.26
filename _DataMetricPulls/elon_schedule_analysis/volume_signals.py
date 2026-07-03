"""What actually drives Elon's daily COUNTED tweet volume (the auction metric)?
Clean X-API only. Counted = counts_main_feed. Window = noon-ET -> noon-ET.
Tests: (1) day-of-week, (2) day-over-day persistence/mean-reversion,
       (3) within-day pacing curve (how early is the total locked in).
"""
import pandas as pd, numpy as np
df = pd.read_parquet('_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet')
df['et'] = pd.to_datetime(df['ts_utc'], utc=True, format='ISO8601').dt.tz_convert('America/New_York')
df = df[df['counts_main_feed']==True].copy()
df['aday'] = (df['et']-pd.Timedelta(hours=12)).dt.date
anchor = (pd.to_datetime(df['aday'])+pd.Timedelta(hours=12)).dt.tz_localize('America/New_York')
df['h_in'] = (df['et'] - anchor).dt.total_seconds()/3600

daily = df.groupby('aday').size().rename('cnt').to_frame()
daily.index = pd.to_datetime(daily.index); daily = daily.sort_index().iloc[1:-1]
print('days:', len(daily), '| median', int(daily['cnt'].median()), 'mean %.1f'%daily['cnt'].mean(),
      'p10 %d p90 %d'%(daily['cnt'].quantile(.1), daily['cnt'].quantile(.9)))

print('\n=== (1) DAY OF WEEK ===')
daily['dow'] = daily.index.dayofweek
names=['Mon','Tue','Wed','Thu','Fri','Sat','Sun']; overall=daily['cnt'].median()
g = daily.groupby('dow')['cnt'].agg(['median','mean','count'])
for d in range(7):
    if d in g.index:
        r=g.loc[d]; print(f'{names[d]}  n={int(r["count"]):3d}  median {r["median"]:4.0f}  mean {r["mean"]:5.1f}  ({r["median"]-overall:+.0f} vs {overall:.0f})')

print('\n=== (2) DAY-OVER-DAY ===')
daily['prev']=daily['cnt'].shift(1); d2=daily.dropna()
print('autocorr lag1 Pearson', round(np.corrcoef(d2['cnt'],d2['prev'])[0,1],3),
      '| Spearman', round(d2[['cnt','prev']].corr(method="spearman").iloc[0,1],3))
q3=daily['cnt'].quantile(.75); q1=daily['cnt'].quantile(.25)
ah=daily[daily['prev']>=q3]['cnt']; al=daily[daily['prev']<=q1]['cnt']
print(f'after HIGH day (prev>=Q3={q3:.0f}): median {ah.median():.0f} mean {ah.mean():.1f} n={len(ah)}')
print(f'after LOW day  (prev<=Q1={q1:.0f}): median {al.median():.0f} mean {al.mean():.1f} n={len(al)}')
print(f'unconditional : median {daily["cnt"].median():.0f} mean {daily["cnt"].mean():.1f}')

print('\n=== (3) WITHIN-DAY PACING (fraction of final done by hour H; predictive corr) ===')
adays=[d.date() for d in daily.index]
sub_by={ad:df[df['aday']==ad] for ad in adays}
for H in [2,4,6,8,10,12,14,16,18,20,22]:
    fr=[]; cs=[]; fs=[]
    for ad in adays:
        s=sub_by[ad]; tot=len(s)
        if tot<5: continue
        so=(s['h_in']<H).sum(); fr.append(so/tot); cs.append(so); fs.append(tot)
    fr=np.array(fr); r=np.corrcoef(cs,fs)[0,1]
    print(f'  H={H:2d}h  median frac {np.median(fr):.2f}  p25 {np.percentile(fr,25):.2f} p75 {np.percentile(fr,75):.2f}   corr(so-far,final)={r:.3f}')
