# -*- coding: utf-8 -*-
"""SPEED STRATEGY, DEPTH-CAPPED, one ENTIRE auction, hold >= 3 min. On every tweet, at T+LATENCY we
BUY the +1 (next-higher) bracket by WALKING THE REAL ASK LADDER (recorder full L2) for a $CLIP, then
after HOLD we SELL by walking the REAL BID LADDER. Total profit summed over the whole auction.
Honesty: depth (size per level) comes from the book snapshots; the fill PRICE at each level is floored
at the dense price_change best-ask at our action time (a stale snapshot can NOT hand us a pre-jump
price). Unsold remainder (thin book) marked at the current best bid. NO look-ahead (+1 from pre-tweet
center; every price read at our action time). Recorder june-27-29 (only auction era with tweets+full L2)."""
import duckdb, sys, glob, os, json, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
REC=glob.glob(ROOT+'/_DataMetricPulls/recordings_pulled/elon-tweets-48h/*.parquet') or glob.glob(ROOT+'/_DataMetricPulls/recordings_pulled/*48h*.parquet')
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; ET=ZoneInfo('America/New_York')
SLUG=os.environ.get('AUCTION','elon-musk-of-tweets-june-27-june-29'); STALE=30000
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
def noon(slug):
    tk=str(slug).replace('elon-musk-of-tweets-','').split('-'); mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
    if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
    else: mo2=mo1;d2=int(tk[2])
    return int(pd.Timestamp(datetime(2026,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(2026,mo2,d2,12,tzinfo=ET)).timestamp())
s,e=noon(SLUG); TAG=SLUG.replace('elon-musk-of-tweets-','')
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
bf=pd.read_parquet(f"{ROOT}/_DataMetricPulls/pacing_backtest/elon_backfill_2025-09_to_now.parquet"); bf=bf[bf.counts_main_feed].sort_values('ms')
bfms=bf.ms.to_numpy().astype('int64'); tw=bfms[(bfms>=s*1000)&(bfms<e*1000)]
arr='['+','.join("'"+f.replace(os.sep,'/')+"'" for f in REC)+']'
pc=con.execute(f"""SELECT ts, bucket, best_bid, best_ask FROM read_parquet({arr},union_by_name=true)
    WHERE slug='{SLUG}' AND event_type='price_change' AND outcome='YES' AND best_bid>0 AND best_ask>0 AND best_ask<1
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
bk=con.execute(f"""SELECT ts, bucket, CAST(data AS VARCHAR) d FROM read_parquet({arr},union_by_name=true)
    WHERE slug='{SLUG}' AND event_type='book' AND outcome='YES' AND data IS NOT NULL
    AND ts>={s*1000} AND ts<{e*1000} ORDER BY ts""").df()
order=sorted(pc.bucket.dropna().unique(), key=lambda l:pbk(l)[0]); idxof={l:i for i,l in enumerate(order)}
PC={}
for l in order:
    sub=pc[pc.bucket==l]
    if len(sub)>=5: PC[l]={'ts':sub.ts.to_numpy().astype('int64'),'bid':sub.best_bid.to_numpy(float),'ask':sub.best_ask.to_numpy(float),'mid':((sub.best_bid+sub.best_ask)/2).to_numpy(float)}
BK={}
for l in order:
    sub=bk[bk.bucket==l]
    if len(sub)==0: continue
    tss=[]; asks=[]; bids=[]
    for _,r in sub.iterrows():
        try: j=json.loads(r.d)
        except Exception: continue
        a=sorted(((float(x['price']),float(x['size'])) for x in j.get('asks',[])), key=lambda z:z[0])
        b=sorted(((float(x['price']),float(x['size'])) for x in j.get('bids',[])), key=lambda z:-z[0])
        if a or b: tss.append(int(r.ts)); asks.append(a); bids.append(b)
    if tss: BK[l]={'ts':np.array(tss,dtype='int64'),'asks':asks,'bids':bids}
print(f"AUCTION {SLUG} | {datetime.fromtimestamp(s,ET):%m-%d %H:%M}->{datetime.fromtimestamp(e,ET):%m-%d %H:%M} ET | tweets {len(tw)} | brackets {len(order)} | book brackets {len(BK)}")
def pc_at(l,t,side):
    d=PC.get(l);
    if not d: return None
    i=np.searchsorted(d['ts'],t,side='right')-1
    return (d[side][i] if i>=0 and (t-d['ts'][i])<=600000 else None)
def book_at(l,t):
    d=BK.get(l)
    if not d: return None
    i=np.searchsorted(d['ts'],t,side='right')-1
    return ((d['asks'][i],d['bids'][i]) if i>=0 and (t-d['ts'][i])<=STALE else None)
def walk_buy(asks,a0,dollars):
    spent=0.0; shares=0.0
    for p,sz in asks:
        pp=max(p,a0); avail=pp*sz; take=min(dollars-spent,avail)
        if take<=1e-9: continue
        shares+=take/pp; spent+=take
        if spent>=dollars-1e-9: break
    return shares,spent
def walk_sell(bids,b0,shares):
    got=0.0; sold=0.0
    for p,sz in bids:
        pp=min(p,b0); take=min(shares-sold,sz)
        if take<=1e-9: continue
        got+=take*pp; sold+=take
        if sold>=shares-1e-9: break
    return got,sold

def run(lat,hold_s,clip):
    tot=0.0; n=0; trades=[]
    for T in tw:
        pre={}
        for l,d in PC.items():
            i=np.searchsorted(d['ts'],T,side='right')-1
            if i>=0 and (T-d['ts'][i])<=300000: pre[l]=d['mid'][i]
        if len(pre)<3: continue
        den=sum(pre.values()); center=sum(pre[l]*bmid(l) for l in pre)/den; rc=round(center)
        cur=None
        for l in order:
            lo,hi=pbk(l)
            if lo<=rc<=hi: cur=l; break
        if cur is None or idxof[cur]+1>=len(order): continue
        p1=order[idxof[cur]+1]; tb=T+lat
        a0=pc_at(p1,tb,'ask'); bkq=book_at(p1,tb)
        if a0 is None or bkq is None: continue
        sh,spent=walk_buy(bkq[0],a0,clip)
        if sh<=1e-9 or spent<=1e-9: continue
        te=tb+hold_s*1000; b0=pc_at(p1,te,'bid'); bkq2=book_at(p1,te)
        if b0 is None: continue
        bids2 = bkq2[1] if bkq2 else [(b0,10**9)]
        got,sold=walk_sell(bids2,b0,sh); rem=sh-sold; got+=rem*b0*0.999   # unsold marked at best bid
        pnl=got-spent; tot+=pnl; n+=1
        trades.append({'et':datetime.fromtimestamp(T/1000,ET).strftime('%m-%d %H:%M:%S'),'bracket':p1,'buy_vwap':round(spent/sh,3),'sell_vwap':round(got/sh,3),'shares':round(sh),'spent':round(spent,1),'pnl':round(pnl,2)})
    return tot,n,trades

print(f"\n=== SPEED STRATEGY, DEPTH-CAPPED, ENTIRE AUCTION. TOTAL PROFIT ($) ===")
grid=[]; best=None
for lat in [250,500]:
    for clip in [100,250,500,1000]:
        for h in [180,300,600]:
            tot,n,trs=run(lat,h,clip)
            grid.append({'auction':TAG,'latency_ms':lat,'clip_$':clip,'hold_min':h//60,'total_profit_$':round(tot),'n_trades':n,
                         'win_rate_%':round(100*(pd.DataFrame(trs).pnl>0).mean(),0) if trs else 0,'mean_$_per_trade':round(tot/n,2) if n else 0})
            if lat==250 and (best is None or tot>best[0]): best=(tot,clip,h,trs)
G=pd.DataFrame(grid); G.to_csv(f"{OUT}/depth_speed_grid_{TAG}.csv",index=False)
print(G[G.latency_ms==250][['clip_$','hold_min','total_profit_$','n_trades','win_rate_%']].to_string(index=False))
if best:
    tot,clip,h,trs=best; T=pd.DataFrame(trs); T.to_csv(f"{OUT}/depth_speed_trades_{TAG}.csv",index=False)
    print(f"\nbest 250ms cell: ${clip}/{h//60}min -> ${tot:+.0f} over {len(T)} trades | win {100*(T.pnl>0).mean():.0f}% | mean ${T.pnl.mean():+.2f}")
    print(f"WROTE depth_speed_grid_{TAG}.csv + depth_speed_trades_{TAG}.csv")
