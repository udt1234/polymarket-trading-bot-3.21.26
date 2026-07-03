"""QA: count each resolved auction from the backfill (locked rule + noon-ET window)
and compare to the official winning bucket."""
import sys, re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON = ROOT/'_DataMetricPulls'/'canonical'; OUT = ROOT/'_DataMetricPulls'/'pacing_backtest'
ET = ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

df = pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet')
df = df[df.counts_main_feed]  # locked rule: only counting posts
ms = df.ms.to_numpy(); ms.sort()
cover_start = pd.Timestamp(df.ts_utc.min()) if isinstance(df.ts_utc.min(),pd.Timestamp) else pd.to_datetime(df['ms'].min(),unit='ms',utc=True)

auc = pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))], ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True); auc['end_utc']=pd.to_datetime(auc['end_utc'],utc=True)

def parse_noonET(slug, ref_year):
    toks=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[toks[0].lower()]; d1=int(toks[1])
        if len(toks)>=4 and toks[2].lower() in MONTHS: mo2=MONTHS[toks[2].lower()]; d2=int(toks[3])
        else: mo2=mo1; d2=int(toks[2])
    except Exception: return None
    y2=ref_year+(1 if mo2<mo1 else 0)
    return (pd.Timestamp(datetime(ref_year,mo1,d1,12,0,tzinfo=ET)).tz_convert('UTC'),
            pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).tz_convert('UTC'))
def parse_bucket(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None

cands = auc[(auc.duration_type.isin(['2-day','7-day'])) & (auc.winning_bucket!='')
            & (~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()

rows=[]
for _,a in cands.iterrows():
    w=parse_noonET(a['auction_slug'], a['start_utc'].year)
    if not w: continue
    ns,ne=w
    if ns < cover_start + pd.Timedelta(hours=2): continue   # window must be fully inside backfill coverage
    cnt=int(np.searchsorted(ms,int(ne.timestamp()*1000)) - np.searchsorted(ms,int(ns.timestamp()*1000)))
    rg=parse_bucket(a['winning_bucket'])
    if not rg: continue
    lo,hi=rg; hi_eff=hi if hi is not None else 10**9
    hit = lo<=cnt<=hi_eff
    mid = lo if hi is None else (lo+hi)/2
    err_mid = abs(cnt-mid)/mid*100 if mid else np.nan
    # distance to bucket (0 if inside)
    dist = 0 if hit else (lo-cnt if cnt<lo else cnt-hi_eff)
    err_edge = dist/cnt*100 if cnt else np.nan
    rows.append({'slug':a['auction_slug'],'dur':a['duration_type'],'conf':a['confidence'],
                 'winner':a['winning_bucket'],'our_count':cnt,'hit':hit,
                 'err_vs_mid%':round(err_mid,1),'edge_miss%':round(err_edge,1)})
r=pd.DataFrame(rows)
print(f"backfill coverage starts: {cover_start}")
print(f"auctions QA'd (window fully covered): {len(r)}")
for dur in ['7-day','2-day']:
    s=r[r.dur==dur]
    if not len(s): continue
    print(f"\n=== {dur}: n={len(s)}  bracket-hit={100*s.hit.mean():.0f}%  median |err vs midpoint|={s['err_vs_mid%'].median():.1f}%  median edge-miss(when miss)={s[~s.hit]['edge_miss%'].median() if (~s.hit).any() else 0:.1f}% ===")
    hc=s[s.conf=='high']
    if len(hc): print(f"    high-conf only: n={len(hc)} bracket-hit={100*hc.hit.mean():.0f}%  median |err|={hc['err_vs_mid%'].median():.1f}%")

print("\n=== per-auction (high-conf, most recent 25) ===")
hc=r[r.conf=='high'].tail(25)
print(hc[['slug','dur','winner','our_count','hit','err_vs_mid%','edge_miss%']].to_string(index=False))
r.to_csv(OUT/'qa_backfill_results.csv', index=False)
print(f"\nfull QA table -> {OUT/'qa_backfill_results.csv'}")
