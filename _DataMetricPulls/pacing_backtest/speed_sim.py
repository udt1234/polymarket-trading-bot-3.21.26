# -*- coding: utf-8 -*-
"""SPEED SIM (Sir's tweet-reaction play), last 24h of every Apr-Jun 2-day auction, event-driven.
TEST B (grab the jump): the instant a tweet posts, at T+LATENCY, BUY $CLIP of the +1 (next-higher)
   bracket at its ask (TAKER - crossing the spread), then SELL at T+LATENCY+HOLD at the bid.
TEST A (dodge the drop): assume we hold $CLIP each of the -1 (early) and 0 (current) brackets;
   at T+LATENCY SELL them at the bid, then REBUY at T+LATENCY+HOLD at the ask. Value = drop dodged.
Both are TAKER by nature (you must cross to react) - that is the tension with the locked maker-only rule.
Sweeps LATENCY {0,250,500,1000,2000 ms} x HOLD {5,15,60 s}. pmxt best bid/ask, $CLIP small (top-of-book
fill assumption, flagged). Cost = the spread (buy ask / sell bid) + FEE. NO look-ahead: bracket chosen
from PRE-tweet center; every fill price is read at our own action time (T+latency), never before."""
import duckdb, sys, glob, os, json, datetime as dt
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"; CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMX=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
ET=ZoneInfo('America/New_York'); MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
CLIP=50.0; FEE=0.0; LAST_H=24; LATS=[0,250,500,1000,2000]; HOLDS=[5,15,60]
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
def bmid(l):
    lo,hi=pbk(l); return lo+12.0 if hi>=10**9 else ((hi+1)/2.0 if lo==0 else (lo+hi)/2.0)
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
    if tok: A.append({'slug':a.auction_slug,'s':s,'e':e,'tok':tok})
def pmxt_files(s,e):
    out=[]; t=datetime.fromtimestamp(s,ET)-dt.timedelta(hours=1); end=datetime.fromtimestamp(e,ET)+dt.timedelta(hours=1)
    while t<=end: out+=glob.glob(f"{PMX}/pmxt_tweets_{t.strftime('%Y-%m-%dT%H')}*.parquet"); t=t+dt.timedelta(hours=1)
    return sorted(set(out))
def at(ts,arr,t):
    i=np.searchsorted(ts,t,side='right')-1
    return (arr[i] if i>=0 and (t-ts[i])<=600000 else None)   # stale-guard 10min

# gather all tweets' bracket books once per auction, then run the sweep in-memory
AU=[]
for a in A:
    s,e=a['s'],a['e']; w0=e-LAST_H*3600
    fs=pmxt_files(w0-120,e)
    if not fs: continue
    arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in fs)+']'
    tok2lab={str(v):k for k,v in a['tok'].items()}; toklist='('+','.join("'"+str(v)+"'" for v in a['tok'].values())+')'
    px=con.execute(f"""SELECT ts, CAST(asset_id AS VARCHAR) aid, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
        WHERE event_type='price_change' AND CAST(asset_id AS VARCHAR) IN {toklist} AND best_ask>0 AND best_ask<1 AND best_bid>0
        AND ts>={(w0-120)*1000} AND ts<{e*1000} ORDER BY ts""").df()
    if len(px)<300: continue
    px['lab']=px.aid.map(tok2lab)
    order=sorted(a['tok'].keys(), key=lambda l:pbk(l)[0]); idxof={l:i for i,l in enumerate(order)}
    B={}
    for l in order:
        sub=px[px.lab==l]
        if len(sub)>=5: B[l]={'ts':sub.ts.to_numpy().astype('int64'),'ask':sub.best_ask.to_numpy(float),'bid':sub.best_bid.to_numpy(float),'mid':((sub.best_bid+sub.best_ask)/2).to_numpy(float)}
    if len(B)<3: continue
    tw=bfms[(bfms>=w0*1000)&(bfms<e*1000)]
    AU.append({'B':B,'order':order,'idxof':idxof,'tw':tw})
print(f"speed sim set: {len(AU)} auctions, {sum(len(x['tw']) for x in AU)} tweets (last {LAST_H}h)")

def run(lat_ms,hold_s):
    rB=[]; rA=[]
    for X in AU:
        B=X['B']; order=X['order']; idxof=X['idxof']
        for T in X['tw']:
            # PRE-tweet center -> current bracket, +1, -1 (no look-ahead: prices strictly < T)
            pre={}
            for l,d in B.items():
                i=np.searchsorted(d['ts'],T,side='right')-1
                if i>=0 and (T-d['ts'][i])<=300000: pre[l]=d['mid'][i]
            if len(pre)<3: continue
            den=sum(pre.values()); center=sum(pre[l]*bmid(l) for l in pre)/den
            rc=round(center); cur=None
            for l in order:
                lo,hi=pbk(l)
                if lo<=rc<=hi: cur=l; break
            if cur is None: continue
            ci=idxof[cur]; tb=T+lat_ms; te=T+lat_ms+hold_s*1000
            # TEST B: buy +1 at ask@tb, sell +1 at bid@te
            if ci+1<len(order) and order[ci+1] in B:
                p1=order[ci+1]; d=B[p1]
                ba=at(d['ts'],d['ask'],tb); sb=at(d['ts'],d['bid'],te)
                if ba and sb and ba>0:
                    sh=CLIP/ba; pnl=sh*sb-CLIP-FEE*CLIP; rB.append(pnl)
            # TEST A: sell -1 & 0 at bid@tb, rebuy at ask@te (value = drop dodged, net of spread)
            for off in (-1,0):
                j=ci+off
                if 0<=j<len(order) and order[j] in B:
                    l=order[j]; d=B[l]; sbid=at(d['ts'],d['bid'],tb); rask=at(d['ts'],d['ask'],te)
                    if sbid and rask and rask>0:
                        # hold shares = CLIP/entry(~sbid); sell now at sbid, rebuy later at rask -> pocket shares*(sbid-rask)
                        shs=CLIP/sbid; pnl=shs*sbid-shs*rask-FEE*CLIP*2; rA.append(pnl)
    return rB,rA

print("\n=== TEST B: buy the +1 bracket on a tweet, sell after HOLD (TAKER). mean P&L per $50 clip (cents) ===")
print(f"{'lat/hold':>10} | " + " ".join(f"{h}s".rjust(9) for h in HOLDS))
for lat in LATS:
    cells=[]
    for h in HOLDS:
        rB,_=run(lat,h); cells.append(f"{100*np.mean(rB):+.2f}({len(rB)})" if rB else "-")
    print(f"{lat:>7}ms | " + " ".join(c.rjust(9) for c in cells))
print("(cents of P&L on a $50 clip; n trades in parens; win needs > 0 after crossing the spread)")

print("\n=== TEST A: sell -1 & current on a tweet, rebuy after HOLD (dodge the drop). mean P&L per $50 clip (cents) ===")
print(f"{'lat/hold':>10} | " + " ".join(f"{h}s".rjust(9) for h in HOLDS))
best=None
for lat in LATS:
    cells=[]
    for h in HOLDS:
        _,rA=run(lat,h); m=100*np.mean(rA) if rA else float('nan'); cells.append(f"{m:+.2f}({len(rA)})" if rA else "-")
    print(f"{lat:>7}ms | " + " ".join(c.rjust(9) for c in cells))
print("\nNOTE: both are TAKER plays. Fills assume $50 fits at top-of-book (small-clip). Depth-capped +")
print("recorder-L2 validation is the next step. FEE set to", FEE)
