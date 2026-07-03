# -*- coding: utf-8 -*-
"""Does a bracket's YES price drift predictably during Elon's SILENCE (dead clusters)?
Tests the user's actual strategy: buy the side that benefits from drift while he's quiet.
Joins hourly bracket close prices with reconstructed running tweet count + posting state."""
import pandas as pd, numpy as np, glob, re, io
from pathlib import Path
OUT=Path("_DataMetricPulls/elon_schedule_analysis"); buf=io.StringIO()
def p(*a): print(*a); print(*a,file=buf)

posts=pd.concat([pd.read_parquet(f) for f in glob.glob("_DataMetricPulls/canonical/posts/elonmusk/*.parquet")],ignore_index=True)
cf=posts[posts.counts_for_auction==True].sort_values("ts_utc")
ts=cf.ts_utc.values.astype("datetime64[s]").astype(np.int64)  # epoch sec
auc=pd.concat([pd.read_parquet(f) for f in glob.glob("_DataMetricPulls/canonical/auctions/elonmusk/*.parquet")],ignore_index=True)
pr=pd.concat([pd.read_parquet(f) for f in glob.glob("_DataMetricPulls/canonical/prices/elonmusk/*.parquet")],ignore_index=True)

MON={m:i for i,m in enumerate(['january','february','march','april','may','june','july','august','september','october','november','december'],1)}
def parse_window(title):
    if not isinstance(title,str): return None
    t=title.lower()
    m=re.search(r'from (\w+) (\d+) to (\w+) (\d+), (\d{4})',t)
    if m and m.group(1) in MON and m.group(3) in MON:
        y=int(m.group(5))
        s=pd.Timestamp(year=y,month=MON[m.group(1)],day=int(m.group(2)),hour=12,tz='America/New_York')
        e=pd.Timestamp(year=y,month=MON[m.group(3)],day=int(m.group(4)),hour=12,tz='America/New_York')
        return s,e
    m=re.search(r'in (\w+) (\d{4})',t)
    if m and m.group(1) in MON:
        y=int(m.group(2)); mo=MON[m.group(1)]
        s=pd.Timestamp(year=y,month=mo,day=1,hour=12,tz='America/New_York')
        e=(s+pd.offsets.MonthBegin(1))
        return s,e
    return None
win={}
for _,r in auc.iterrows():
    w=parse_window(r.title)
    if w: win[r.auction_slug]=w
p(f"auctions with parseable window: {len(win)}")

def run_count(s,e): # qualifying posts in [s,e)
    return int(np.searchsorted(ts,e)-np.searchsorted(ts,s))
def bucket_lohi(lbl):
    lbl=lbl.strip()
    if lbl.startswith('<'): return (0,int(lbl[1:])-1)
    if lbl.endswith('+'): return (int(lbl[:-1]),10**9)
    if '-' in lbl:
        a,b=lbl.split('-'); return (int(a),int(b))
    return None

pr=pr[pr.auction_slug.isin(win)].copy()
pr=pr[pr.hour_utc>= "2025-11-01"]   # repost-complete era
rows=[]
for (slug,bucket),g in pr.groupby(["auction_slug","bucket"]):
    lh=bucket_lohi(bucket)
    if not lh: continue
    lo,hi=lh; s,e=win[slug]
    g=g.sort_values("hour_utc")
    closes=g.close.values; hours=pd.to_datetime(g.hour_utc.values, utc=True)
    for i in range(1,len(g)):
        h=hours[i]
        if h< s or h> e: continue
        sec=h.value//10**9
        rc=run_count(s.value//10**9, sec)          # running count up to this hour
        # posted in the trailing hour?
        prev_sec=sec-3600
        posted = (np.searchsorted(ts,sec)-np.searchsorted(ts,prev_sec))>0
        dprice=closes[i]-closes[i-1]
        if abs(dprice)>0.5: continue                # skip resolution jumps/garbage
        pos='below' if rc<lo else ('inside' if rc<=hi else 'above')
        rows.append((closes[i-1],dprice,posted,pos))
D=pd.DataFrame(rows,columns=["px","dpx","posted","pos"])
p(f"bracket-hours analyzed (Nov2025+, in-window): {len(D):,}")

p("\n=== mean hourly YES-price change by bracket position x posting state ===")
p(f"{'position':>8} {'state':>8} {'n':>7} {'mean_dpx(cents/hr)':>20} {'median':>8}")
for pos in ['below','inside','above']:
    for posted,lbl in [(False,'SILENT'),(True,'POSTED')]:
        sub=D[(D.pos==pos)&(D.posted==posted)]
        if len(sub)<30: continue
        p(f"{pos:>8} {lbl:>8} {len(sub):>7,} {sub.dpx.mean()*100:>19.2f}c {sub.dpx.median()*100:>7.2f}c")

p("\n=== the user's exact play: mid-priced YES (0.45-0.85) bracket, by state ===")
mid=D[(D.px>=0.45)&(D.px<=0.85)]
for posted,lbl in [(False,'SILENT'),(True,'POSTED')]:
    sub=mid[mid.posted==posted]
    p(f"  {lbl}: n={len(sub):,}  mean dpx={sub.dpx.mean()*100:+.2f}c/hr  P(drop)={ (sub.dpx<0).mean()*100:.0f}%")

p("\n=== drift vs SILENCE LENGTH (below-bracket YES, should decay as he stays dead) ===")
# recompute silence length for below-position mid brackets
bel=D[(D.pos=='below')]
# (silence length not stored per-row; approximate via posting state only here)
p("  (below-bracket YES during SILENT hours = the drift you harvest by buying NO)")
sub=bel[bel.posted==False]; sub2=bel[bel.posted==True]
p(f"  SILENT below-bracket: mean dpx={sub.dpx.mean()*100:+.2f}c/hr  (negative = YES decays, NO rises -> your margin)")
p(f"  POSTED below-bracket: mean dpx={sub2.dpx.mean()*100:+.2f}c/hr  (positive = burst snaps it back -> your risk)")

(OUT/"SILENCE_DRIFT_REPORT.txt").write_text(buf.getvalue(),encoding="utf-8")
p("\n[wrote SILENCE_DRIFT_REPORT.txt]")
