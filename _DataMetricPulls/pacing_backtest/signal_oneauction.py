# -*- coding: utf-8 -*-
"""YOUR strategy, SIGNALS ONLY (no fills, no P&L), on ONE auction.
Fair value = AccrualCurve (our engine): our_count = posts_so_far / typical_share_done_by_now
             (walk-forward share curve, embeds sleep). NOT the naive linear Kalman.
Market view = reverse-pace: market_count = sum(bracket_center * normalized market price).
EDGE = divergence (our_count - market_count). We BUY the bracket our pace points to when the
market underprices it (divergence opens), and CLOSE when the divergence converges. In and out.
Output = the trade signals. This does NOT simulate fills or compute money."""
import duckdb, sys, math, json, glob, os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
sys.stdout.reconfigure(encoding='utf-8'); con=duckdb.connect()
ROOT="C:/Users/darwi/OneDrive/Desktop/Claude Code/Personal/PolyMarket_Bot"
CANON=f"{ROOT}/_DataMetricPulls/canonical"; PMXT=f"{ROOT}/_DataMetricPulls/pmxt_pulled"
OUT=f"{ROOT}/_DataMetricPulls/pacing_backtest/audit_out3"; os.makedirs(OUT,exist_ok=True)
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
def center(lo,hi): return (lo+15) if hi>=10**8 else (lo+hi)/2.0
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
        y2=yr+(1 if mo2<mo1 else 0)
        return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
    except: return None
# ---- AccrualCurve share curve (walk-forward), from accrual_model.py ----
def build_share(dur_h, before_ts):
    noon0=pd.Timestamp(datetime.fromtimestamp(c0,ET).date(),tz=ET)+pd.Timedelta(hours=12); d=noon0; curves=[]
    while d.timestamp()+dur_h*3600<=before_ts:
        ss=int(d.timestamp()); ee=ss+dur_h*3600; final=obs(ss,ee)
        if final>=5: curves.append(np.array([obs(ss,ss+h*3600) for h in range(1,dur_h+1)],float)/final)
        d=d+pd.Timedelta(days=1)
    return (np.clip(np.median(np.vstack(curves),axis=0),1e-3,1.0) if curves else None)

# ---- pick the most active 2-day auction with L2 ----
auc=pd.concat([pd.read_parquet(p) for p in sorted(glob.glob(f"{CANON}/auctions/elonmusk/*.parquet"))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
L2START=int(datetime(2026,4,13,19,tzinfo=timezone.utc).timestamp())
cands=[]
for _,a in auc.iterrows():
    if a.duration_type!='2-day' or str(a.confidence) not in ('high','medium'): continue
    w=noon(a.auction_slug,a['start_utc'].year)
    if not w: continue
    s,e=w
    if not(1.5<=(e-s)/86400<=2.6) or e>c1 or e<L2START+2*86400: continue
    try: tm=json.loads(a.bracket_yes_token_ids)
    except: continue
    t2b={t:l for l,t in tm.items() if isinstance(t,str) and t.isdigit() and len(t)>18 and pbk(l)}
    if len(t2b)>=4: cands.append({'slug':a.auction_slug,'s':s,'e':e,'t2b':t2b,'winner':str(a.winning_bucket)})
def l2files(s,e):
    fs=[];h=datetime.fromtimestamp(s,timezone.utc).replace(minute=0,second=0,microsecond=0);endh=datetime.fromtimestamp(e,timezone.utc)
    while h<=endh:
        p=f"{PMXT}/pmxt_tweets_{h:%Y-%m-%dT%H}.parquet"
        if os.path.exists(p): fs.append(p)
        h+=timedelta(hours=1)
    return fs
# choose the candidate with the most price rows
best=None; bestn=0
for a in cands:
    files=l2files(a['s'],a['e'])
    if len(files)<20: continue
    arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in a['t2b'])+")"
    n=q(f"SELECT count(*) c FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change'").c.iloc[0]
    if n>bestn: bestn=n; best=a
A=best; s,e=A['s'],A['e']; total=(e-s)/3600
print(f"AUCTION: {A['slug']} | official winner {A['winner']} | actual final {obs(s,e)} tweets | {int(bestn)} price rows")

# ---- per 10-min bar: last mid per bracket ----
files=l2files(s,e); arr="["+",".join("'"+f.replace(os.sep,'/')+"'" for f in files)+"]"; toks="("+",".join("'"+t+"'" for t in A['t2b'])+")"
px=q(f"""SELECT asset_id,(ts//600000)*600000 bar, arg_max(best_bid,ts) bid, arg_max(best_ask,ts) ask
    FROM read_parquet({arr},union_by_name=true) WHERE asset_id IN {toks} AND event_type='price_change' AND best_ask>0 AND best_ask<1 AND ts>={s*1000} AND ts<{e*1000} GROUP BY 1,2""")
px['bucket']=px.asset_id.map(A['t2b']); px['mid']=np.where(px.bid>0,(px.bid+px.ask)/2,px.ask)
grid=px.pivot_table(index='bar',columns='bucket',values='mid',aggfunc='last').sort_index().ffill()
brs={b:pbk(b) for b in grid.columns if pbk(b)}
share=build_share(48,s)
print(f"AccrualCurve share @ 6h/12h/24h/36h = {share[5]:.2f}/{share[11]:.2f}/{share[23]:.2f}/{share[35]:.2f}")

# ---- signal loop (NO fills) ----
ENTER=5.0; EXIT=2.0
rows=[]; trades=[]; pos=None
for bar in grid.index:
    t=bar/1000.0; elapsed=(t-s)/3600.0
    if elapsed<3 or elapsed>total-0.3: continue
    o=obs(s,int(t)); idx=min(len(share)-1,max(0,int(elapsed)-1))
    our=o/share[idx]                                    # AccrualCurve projection
    prices={b:grid.loc[bar,b] for b in brs if pd.notna(grid.loc[bar,b]) and grid.loc[bar,b]>0}
    tot=sum(prices.values())
    if tot<=0: continue
    mkt=sum(center(*brs[b])*(p/tot) for b,p in prices.items())   # reverse-pace market count
    div=our-mkt
    target=next((b for b,(lo,hi) in brs.items() if lo<=round(our)<=hi),None)
    action=''
    if pos is None:
        if abs(div)>=ENTER and target and target in prices:
            pos={'b':target,'entry_px':prices[target],'entry_div':div}; action=f"BUY {target}"
            trades.append({'action':'BUY','bracket':target,'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),
                'tweets':o,'our_count':round(our,1),'mkt_count':round(mkt,1),'divergence':round(div,1),
                'price':round(prices[target],3),'reason':f"our pace {our:.0f} vs market {mkt:.0f} -> {'UP' if div>0 else 'DOWN'} edge {abs(div):.0f}"})
    else:
        held=pos['b']; hp=prices.get(held,np.nan)
        if abs(div)<=EXIT or target!=held:
            action=f"SELL {held}"
            trades.append({'action':'SELL','bracket':held,'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),
                'tweets':o,'our_count':round(our,1),'mkt_count':round(mkt,1),'divergence':round(div,1),
                'price':round(hp,3) if pd.notna(hp) else None,'reason':('divergence converged (<=%.0f)'%EXIT) if abs(div)<=EXIT else f"pace moved to {target}"})
            pos=None
            if target and target in prices and abs(div)>=ENTER:
                pos={'b':target,'entry_px':prices[target],'entry_div':div}
                trades.append({'action':'BUY','bracket':target,'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),
                    'tweets':o,'our_count':round(our,1),'mkt_count':round(mkt,1),'divergence':round(div,1),
                    'price':round(prices[target],3),'reason':f"rotate: our pace now points to {target}"})
    rows.append({'et':datetime.fromtimestamp(t,ET).strftime('%m-%d %H:%M'),'elapsed_h':round(elapsed,1),'tweets':o,
        'our_count(Accrual)':round(our,1),'mkt_count(revpace)':round(mkt,1),'divergence':round(div,1),
        'target_bracket':target,'in_position':pos['b'] if pos else '','action':action})
td=pd.DataFrame(trades); series=pd.DataFrame(rows)
td.to_csv(f"{OUT}/signals.csv",index=False); series.to_csv(f"{OUT}/timeline.csv",index=False)
nb=len(td[td.action=='BUY']); nsx=len(td[td.action=='SELL'])
print(f"\nSIGNALS: {len(td)} orders ({nb} BUY, {nsx} SELL) across {len(series)} evaluated bars")
print("first 20 signals:")
for _,r in td.head(20).iterrows():
    print(f"  {r.et} | {r.action:<9} | our {r.our_count:>5} vs mkt {r.mkt_count:>5} | div {r.divergence:>+5} | px {r.price} | {r.reason}")
print(f"\nWROTE {OUT}/signals.csv + timeline.csv")
