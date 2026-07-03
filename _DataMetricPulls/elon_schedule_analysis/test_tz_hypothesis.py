"""Test: does Elon's ET posting START time shift with his physical timezone?
 H1: Central(TX) mornings start earlier in ET; Pacific(CA) mornings start later.
 Merge whereabouts.csv (date,tz) with session_starts.csv on session 'day'.
"""
import pandas as pd, numpy as np
from pathlib import Path
D = Path('_DataMetricPulls/elon_schedule_analysis')

s = pd.read_csv(D/'session_starts.csv', parse_dates=['day'])
w = pd.read_csv(D/'whereabouts.csv', parse_dates=['date']).rename(columns={'date':'day'})
rank = {'high':2,'med':1,'low':0}
w['r'] = w['conf'].map(rank).fillna(0)
w = w.sort_values('r').drop_duplicates('day', keep='last')

# If multiple sessions in a day, keep the FIRST (the morning wake) session.
s = s.sort_values('start').drop_duplicates('day', keep='first')
m = s.merge(w[['day','tz','conf','source_type']], on='day', how='inner')
print('labeled active posting-days:', len(m), '| tz:', dict(m['tz'].value_counts()))

def clk(x):
    x=x%24; h=int(x); mn=int(round((x-h)*60)); h+=mn//60; mn%=60
    ap='AM' if (h%24)<12 else 'PM'; return f'{(h%24)%12 or 12}:{mn:02d}{ap}'

print('\n--- ET START time by physical timezone ---')
for tz in ['CT','PT','ET','OTHER']:
    b = m[m['tz']==tz]['start_min']
    if len(b)==0: continue
    print(f'{tz:5s} n={len(b):3d}  median {clk(np.median(b))}  mean {b.mean():5.1f}h  p25={np.percentile(b,25):4.1f} p75={np.percentile(b,75):4.1f}')

ct = m[m['tz']=='CT']['start_min']; pt = m[m['tz']=='PT']['start_min']
print(f'\nCT n={len(ct)}  PT n={len(pt)}')
if len(ct)>=4 and len(pt)>=4:
    gap = np.median(pt)-np.median(ct)
    print(f'median ET-start gap (PT - CT) = {gap:+.2f}h  (constant-body-clock predicts ~+2h; partial-adjust 0..2h; 0 = no effect)')
    try:
        from scipy import stats
        u,p = stats.mannwhitneyu(pt, ct, alternative='greater')
        print(f'Mann-Whitney one-sided (PT later): U={u:.0f} p={p:.4f}')
    except Exception as e:
        print('scipy unavailable:', e)

print('\n--- per-day detail (sorted by tz then start) ---')
for _,r in m.sort_values(['tz','start_min']).iterrows():
    print(f'{r.day.date()} {r.tz:5s} {r.conf:4s} start {clk(r.start_min):7s} end_abs {r.end_abs:4.1f}h n={int(r.n):3d} vol={r.mf_count}  {r.source_type}')
