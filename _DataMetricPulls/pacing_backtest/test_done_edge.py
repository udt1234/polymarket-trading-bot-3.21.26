# -*- coding: utf-8 -*-
"""DECISIVE PREMISE TEST for the 'he's done' edge, BEFORE building any strategy on it.
Measures: when our lock-detector knows the winning bracket, what is the market still paying for it?
If the market already pays ~0.95, there is NO edge and we do not build S2."""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
pts=(bf.ms.to_numpy()//1000).astype('int64'); c0,c1=int(pts.min()),int(pts.max())
def obs(s,e): return int(np.searchsorted(pts,e)-np.searchsorted(pts,s))
def q(x): return con.execute(x).df()
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
print("building plausible-remaining table (q95 of tweets in an L-hour window)...")
Q95={}
starts=np.arange(c0, c1-48*3600, 3600)
for L in range(1,49):
    cnt=np.searchsorted(pts,starts+L*3600)-np.searchsorted(pts,starts)
    Q95[L]=int(np.percentile(cnt,95))
print("  q95 tweets in next 1h/3h/6h/12h/24h =",Q95[1],Q95[3],Q95[6],Q95[12],Q95[24])
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp())
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
rows=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w
    if not(1.5<=(e-s)/86400<=2.6) or e>c1 or e<L2START: continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    t2b={t:l for l,t in tm.items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
    W=str(a.winning_bucket).strip(); wb=pbk(W)
    if len(t2b)<3 or not wb: continue
    files=l2files(s,e)
    if len(files)<20: continue
    arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in t2b)+")"
    px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask
        FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
    if px.empty: continue
    px['bucket']=px.asset_id.map(t2b); px['mid']=np.where(px.bid>0,(px.bid+px.ask)/2,px.ask)
    grid=px.pivot_table(index='bar',columns='bucket',values='mid',aggfunc='last').sort_index().ffill()
    if W not in grid.columns: continue
    brks={b:pbk(b) for b in grid.columns if pbk(b)}
    Tsig=None; sigb=None; pxsig=None; Tmkt=None
    for bar in grid.index:
        t=bar/1000.0; rem=(e-t)/3600.0
        if rem<=0.05: break
        o=obs(s,int(t)); L=max(1,min(48,int(math.ceil(rem))))
        if Tsig is None:
            cur=next((b for b,(lo,hi) in brks.items() if lo<=o<=hi),None)
            if cur:
                lo,hi=brks[cur]
                if hi<10**8 and Q95[L] <= (hi-o):
                    Tsig=t; sigb=cur; pxsig=float(grid.loc[bar,cur]) if cur in grid.columns and pd.notna(grid.loc[bar,cur]) else np.nan
        if Tmkt is None and pd.notna(grid.loc[bar,W]) and grid.loc[bar,W]>=0.90: Tmkt=t
        if Tsig and Tmkt: break
    if Tsig is None:
        rows.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'winner':W,'sig_bracket':'never','hrs_before_close':None,'price_at_signal':None,'lead_hrs':None,'correct':None}); continue
    rows.append({'slug':a.auction_slug.replace('elon-musk-of-tweets-',''),'winner':W,'sig_bracket':sigb,
        'hrs_before_close':round((e-Tsig)/3600,2),'price_at_signal':round(pxsig,3) if pxsig==pxsig else None,
        'lead_hrs':round((Tmkt-Tsig)/3600,2) if Tmkt else None,'correct':(sigb==W)})
r=pd.DataFrame(rows)
pd.set_option('display.width',200)
print(f"\n=== LOCK-DETECTOR vs THE MARKET (n={len(r)} two-day auctions with L2) ===")
print(r.to_string(index=False))
ok=r[r.hrs_before_close.notna()]
if len(ok):
    print(f"\nfired on {len(ok)}/{len(r)} auctions | picked the correct bracket {int(ok.correct.sum())}/{len(ok)}")
    print(f"MEDIAN market price for that bracket AT THE MOMENT WE KNEW: {ok.price_at_signal.median():.3f}   <-- THE NUMBER")
    print(f"MEDIAN hours before close we knew: {ok.hrs_before_close.median():.2f}h")
    ld=ok[ok.lead_hrs.notna()]
    if len(ld): print(f"MEDIAN LEAD over market's own 0.90 confidence: {ld.lead_hrs.median():+.2f}h (positive = we knew first)")
    print("\nVERDICT RULE: price@signal ~0.95 => NO edge, do not build S2. price@signal 0.5-0.8 with hours of lead => real edge.")
