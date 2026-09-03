# -*- coding: utf-8 -*-
"""FEASIBILITY GATE for the speed play (v2 - eventful tweets, offset-from-current classification).
The MEDIAN tweet moves nothing (most tweets are non-events). The tradeable signal is the EVENTFUL
tweet (one that actually moved the book >=2c somewhere). For those, measure the SIGNED move of each
bracket by its OFFSET from the current bracket (-2,-1,0,+1,+2, far), at ms windows, + the market's
reaction ONSET (latency budget) + how OFTEN a tweet is eventful. Directly tests Sir's 3 claims:
  offset<0 (early) DROPS, offset 0 (current) ~flat, offset>0 (long) JUMPS, and how fast/how often.
Data: pmxt YES top-of-book via bracket_yes_token_ids + X-API tweet times (ms). Last 24h of each auction."""
import duckdb, sys, glob, os, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
WINS=[500,1000,2000,5000,15000,60000,300000]; LAST_H=24; EVENT=0.02
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
bfms=bf.ms.to_numpy().astype('int64'); c0,c1=int(bfms.min()//1000),int(bfms.max()//1000)
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),10**9)
        if '-' in l: a,b=l.split('-'); return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def noon(slug):
    try:
        tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
    except Exception: return None
auc=pd.concat([pd.read_parquet(p) for p in glob.glob(f"{CANON}/auctions/elonmusk/*.parquet")],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True,errors='coerce'); A=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    if str(a.resolution_status) not in ('resolved_yes','resolved_yes_gamma'): continue
    w=noon(a.auction_slug)
    if not w: continue
    s,e=w
    if not 1.5<=(e-s)/86400<=2.6 or e>c1 or s<c0+7200: continue
    tok=a.bracket_yes_token_ids; tok=json.loads(tok) if isinstance(tok,str) else dict(tok)
    if not tok: continue
    A.append({'slug':a.auction_slug,'s':s,'e':e,'tok':tok})
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
def at(ts,arr,t):
    i=np.searchsorted(ts,t,side='right')-1
    return (arr[i] if i>=0 else None)

recs=[]; onsets=[]; nau=0; ntw=0; nevent=0
for a in A:
    s,e=a['s'],a['e']; w0=e-LAST_H*3600
    fs=pmxt_files(w0-120,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    tok2lab={str(v):k for k,v in a['tok'].items()}; toklist='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1
        AND ts>={(w0-120)*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<300: continue
    px['lab']=px.aid.map(tok2lab); px['mid']=np.where(px.best_bid>0,(px.best_bid+px.best_ask)/2,px.best_ask)
    order=sorted(a['tok'].keys(), key=lambda l:pbk(l)[0]); rng={l:pbk(l) for l in order}; idxof={l:i for i,l in enumerate(order)}
    B={}
    for l in order:
        sub=px[px.lab==l]
        if len(sub)>=5: B[l]={'ts':sub.ts.to_numpy().astype('int64'),'ask':sub.best_ask.to_numpy(float),'bid':sub.best_bid.to_numpy(float),'mid':sub.mid.to_numpy(float)}
    if len(B)<3: continue
    tw=bfms[(bfms>=w0*1000)&(bfms<e*1000)]
    if len(tw)==0: continue
    nau+=1
    for T in tw:
        pre={}
        for l,d in B.items():
            i=np.searchsorted(d['ts'],T,side='right')-1
            if i>=0 and (T-d['ts'][i])<=300000: pre[l]={'mid':d['mid'][i],'ask':d['ask'][i],'bid':d['bid'][i]}
        if len(pre)<3: continue
        ntw+=1
        den=sum(pre[l]['mid'] for l in pre); center=sum(pre[l]['mid']*(pbk(l)[0]+12 if pbk(l)[1]>=10**9 else (pbk(l)[1]+1)/2 if pbk(l)[0]==0 else (pbk(l)[0]+pbk(l)[1])/2) for l in pre)/den if den>0 else None
        if center is None: continue
        rc=round(center); cur=None
        for l in order:
            lo,hi=rng[l]
            if lo<=rc<=hi: cur=l; break
        if cur is None: continue
        ci=idxof[cur]
        # move at 60s for every bracket -> eventfulness + onset
        mv60={}; onmin=None
        for l,d in pre.items():
            m60=at(B[l]['ts'],B[l]['mid'],T+60000); mv60[l]=(m60-d['mid']) if m60 is not None else 0.0
            j=np.searchsorted(B[l]['ts'],T,side='left')
            while j<len(B[l]['ts']) and B[l]['ts'][j]-T<=300000:
                if abs(B[l]['mid'][j]-d['mid'])>=EVENT: onmin=min(onmin,B[l]['ts'][j]-T) if onmin else (B[l]['ts'][j]-T); break
                j+=1
        eventful = max(abs(v) for v in mv60.values())>=EVENT
        if eventful: nevent+=1
        if onmin is not None and eventful: onsets.append(onmin)
        for l in pre:
            off=idxof[l]-ci; offb = off if -2<=off<=2 else (3 if off>2 else -3)
            row={'slug':a['slug'].replace('elon-musk-of-tweets-',''),'eventful':eventful,'offset':offb,'pre_mid':round(pre[l]['mid'],3)}
            for W in WINS:
                mv=at(B[l]['ts'],B[l]['mid'],T+W); row[f'd{W}']=(mv-pre[l]['mid']) if mv is not None else np.nan
            recs.append(row)
R=pd.DataFrame(recs); R.to_csv(f"{OUT}/tweet_reaction.csv",index=False)
lab={500:'0.5s',1000:'1s',2000:'2s',5000:'5s',15000:'15s',60000:'60s',300000:'5min'}
print(f"auctions: {nau} | tweets analyzed: {ntw} | EVENTFUL (moved book >= {EVENT}): {nevent} ({100*nevent/max(ntw,1):.0f}%)")
if len(onsets): oa=np.array(onsets); print(f"reaction ONSET on eventful tweets: median {np.median(oa):.0f}ms | p25 {np.percentile(oa,25):.0f} | p75 {np.percentile(oa,75):.0f}  <- latency budget (n={len(oa)})")
ev=R[R.eventful]
print(f"\n=== EVENTFUL tweets: MEAN SIGNED mid move (cents) by offset-from-current x window (n obs) ===")
rows=[]
for off,name in [(-3,'<= -3 (far low)'),(-2,'-2'),(-1,'-1 (early)'),(0,'0 (current)'),(1,'+1 (long)'),(2,'+2'),(3,'>= +3 (far long)')]:
    sub=ev[ev.offset==off]; row={'offset':name,'n':len(sub)}
    for W in WINS: row[lab[W]]=round(100*sub[f'd{W}'].mean(),2) if len(sub) else np.nan
    rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))
print(f"\n=== SPEED: |60s move| realized by each window (eventful, offset +1/+2 = the jump), % of 60s move ===")
hi=ev[ev.offset.isin([1,2])]; full=hi['d60000'].abs().mean()
if full and full>0: print({lab[W]:round(100*hi[f'd{W}'].abs().mean()/full,0) for W in WINS})
print(f"\nWROTE {OUT}/tweet_reaction.csv")
