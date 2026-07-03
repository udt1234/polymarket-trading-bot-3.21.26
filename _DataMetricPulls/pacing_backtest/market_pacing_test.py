"""Test the theory: (A) is the MARKET's own bracket pricing a better bracket-picker than our
models (i.e. is the market the best pacer we should reverse-engineer)? and (B) does the market
OVERREACT to tweets and then revert (the edge lives in the deviations)?  Uses what we already
have: clob_prices (1-min per-bracket) + X-API tweet times + canonical winners."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd
from pathlib import Path
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'; CANON=ROOT/'_DataMetricPulls'/'canonical'; ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}
bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms').reset_index(drop=True)
post_ts=(bf.ms.to_numpy()//1000).astype('int64'); cover0,cover1=int(post_ts.min()),int(post_ts.max())
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
prc=pd.read_parquet(OUT/'clob_prices.parquet').sort_values(['auction_slug','bucket','t'])
pidx={}
for (sl,bk),g in prc.groupby(['auction_slug','bucket']): pidx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
buckets_by=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
def price_at(sl,bk,t):
    a=pidx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noon(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except Exception: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,tzinfo=ET)).timestamp()))
cand=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))].copy()
sel=[]
for _,a in cand.iterrows():
    w=noon(a['auction_slug'],a['start_utc'].year)
    if not w: continue
    s,e=w; dur=a['duration_type']; days=(e-s)/86400
    if dur=='7-day' and not 6.5<=days<=7.6: continue
    if dur=='2-day' and not 1.5<=days<=2.6: continue
    if a['auction_slug'] not in buckets_by: continue           # need market prices
    sel.append({'slug':a['auction_slug'],'dur':dur,'s':s,'e':e,'winner':str(a['winning_bucket'])})
print(f"auctions with market prices: {len(sel)} ({sum(1 for x in sel if x['dur']=='2-day')} 2d, {sum(1 for x in sel if x['dur']=='7-day')} 7d)\n")

# ---- (A) market bracket-hit: is the market favorite the winning bracket? ----
print("=== (A) MARKET as a bracket-picker (favorite = highest-priced bracket) ===")
print(f"{'horizon':<8}{'2-day mkt':>11}{'7-day mkt':>11}  (compare: our best model ~44% @24h, ~80-90% @1h)")
for hr in [24,1]:
    res={'2-day':[],'7-day':[]}
    for a in sel:
        cps=a['e']-hr*3600
        if cps<=a['s']+3600: continue
        prices={bk:price_at(a['slug'],bk,cps) for bk in buckets_by[a['slug']]}
        prices={bk:p for bk,p in prices.items() if p is not None}
        if not prices: continue
        fav=max(prices,key=prices.get)
        res[a['dur']].append(1 if fav==a['winner'] else 0)
    print(f"T-{'1d' if hr==24 else '1h':<5}{100*np.mean(res['2-day']) if res['2-day'] else float('nan'):>9.0f}% ({len(res['2-day'])})"
          f"{100*np.mean(res['7-day']) if res['7-day'] else float('nan'):>8.0f}% ({len(res['7-day'])})")

# ---- (B) tweet reaction + reversion: does a tweet move the market, and does it overshoot? ----
print("\n=== (B) tweet reaction (1-min bars; the FAVORITE bracket's price moves) ===")
tweet_abs=[]; notweet_abs=[]; revert=[]
for a in sel:
    s,e=a['s'],a['e']; slug=a['slug']
    # pick the bracket that was favorite at mid-auction to track
    mid=(s+e)//2
    pr={bk:price_at(slug,bk,mid) for bk in buckets_by[slug]}; pr={k:v for k,v in pr.items() if v}
    if not pr: continue
    track=max(pr,key=pr.get)
    arr=pidx.get((slug,track))
    if arr is None: continue
    ts,ps=arr
    tw=set((post_ts[(post_ts>=s)&(post_ts<e)]//60)*60)   # minute-of-tweet timestamps
    for i in range(1,len(ts)-30):
        dt=ts[i]-ts[i-1]
        if dt>120: continue                               # only contiguous 1-min steps
        move=ps[i]-ps[i-1]
        minute=(ts[i]//60)*60
        if minute in tw or (minute-60) in tw:
            tweet_abs.append(abs(move))
            # reversion: of the move at i, how much is undone over next 30 min?
            fwd=ps[min(i+30,len(ps)-1)]-ps[i]
            if abs(move)>0.01: revert.append(-fwd/move)   # >0 = reverted
        else:
            notweet_abs.append(abs(move))
print(f"avg |1-min price move| on TWEET minutes : {np.mean(tweet_abs)*100:.2f}c   (n={len(tweet_abs)})")
print(f"avg |1-min price move| on QUIET minutes : {np.mean(notweet_abs)*100:.2f}c   (n={len(notweet_abs)})")
print(f"ratio (tweet/quiet): {np.mean(tweet_abs)/max(1e-9,np.mean(notweet_abs)):.2f}x  -> {'market REACTS to tweets' if np.mean(tweet_abs)>np.mean(notweet_abs) else 'no reaction'}")
rv=np.array(revert); rv=rv[np.isfinite(rv)]
print(f"\nreversion over 30 min after a tweet-shock (>0 = price gives back the move):")
print(f"  median {np.median(rv):.2f}  mean {np.mean(rv):.2f}  | % that revert >0: {100*np.mean(rv>0):.0f}%  (n={len(rv)})")
print("  >0.30 median would be a real overreaction/seesaw edge; ~0 = efficient; <0 = momentum")
