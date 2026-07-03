"""FINISH-LINE edge test. In the last few hours, the count is nearly locked, so we estimate
the final settle count tightly (observed + Poisson(recent_rate x remaining)), turn it into a
bracket probability q, and compare to the market price p. Where q > p + GAP we BUY and hold to
resolution. Measures predicted EV (q-p) vs REALIZED PnL (payoff - p). If realized PnL is
positive net of cost, a finish-line edge exists. Walk-forward not needed (no cross-auction
params; each auction uses only its own observed tweets + live prices)."""
import sys, math
from datetime import datetime
from zoneinfo import ZoneInfo
import numpy as np, pandas as pd, json
from pathlib import Path
from scipy.stats import poisson
sys.stdout.reconfigure(encoding='utf-8')
ROOT=Path(r'C:\Users\darwi\OneDrive\Desktop\Claude Code\Personal\PolyMarket_Bot')
CANON=ROOT/'_DataMetricPulls'/'canonical'; OUT=ROOT/'_DataMetricPulls'/'pacing_backtest'
ET=ZoneInfo('America/New_York')
MONTHS={m.lower():i for i,m in enumerate(['','January','February','March','April','May','June','July','August','September','October','November','December'])}

bf=pd.read_parquet(OUT/'elon_backfill_2025-09_to_now.parquet'); bf=bf[bf.counts_main_feed].sort_values('ms')
post_ts=(bf.ms.to_numpy()//1000).astype('int64')
def obs(s,e): return int(np.searchsorted(post_ts,e)-np.searchsorted(post_ts,s))
prc=pd.read_parquet(OUT/'clob_prices.parquet')
price_idx={}
for (sl,bk),g in prc.sort_values('t').groupby(['auction_slug','bucket']):
    price_idx[(sl,bk)]=(g['t'].to_numpy(),g['price'].to_numpy())
def price_at(sl,bk,t):
    a=price_idx.get((sl,bk))
    if a is None: return None
    ts,ps=a; i=np.searchsorted(ts,t,side='right')-1
    if i<0: return None
    v=float(ps[i]); return v if 0<v<1 else None
buckets_by_slug=prc.groupby('auction_slug')['bucket'].apply(lambda s:sorted(set(s.dropna()))).to_dict()
auc=pd.concat([pd.read_parquet(p) for p in sorted((CANON/'auctions/elonmusk').glob('*.parquet'))],ignore_index=True)
auc['start_utc']=pd.to_datetime(auc['start_utc'],utc=True)
def noonET(slug,yr):
    tk=slug.replace('elon-musk-of-tweets-','').split('-')
    try:
        mo1=MONTHS[tk[0].lower()];d1=int(tk[1])
        if len(tk)>=4 and tk[2].lower() in MONTHS: mo2=MONTHS[tk[2].lower()];d2=int(tk[3])
        else: mo2=mo1;d2=int(tk[2])
    except: return None
    y2=yr+(1 if mo2<mo1 else 0)
    return (int(pd.Timestamp(datetime(yr,mo1,d1,12,0,tzinfo=ET)).timestamp()),int(pd.Timestamp(datetime(y2,mo2,d2,12,0,tzinfo=ET)).timestamp()))
def pbk(l):
    l=str(l).strip()
    try:
        if l.startswith('<'): return (0,int(l[1:])-1)
        if l.endswith('+'): return (int(l[:-1]),None)
        if '-' in l: a,b=l.split('-');return (int(a),int(b))
        return (int(l),int(l))
    except: return None
def bracket_prob(lo,hi,observed,lam):
    # P(observed + remaining in [lo,hi]), remaining ~ Poisson(lam)
    if hi is None: return max(1e-9, 1.0-poisson.cdf(lo-observed-1, lam))
    return max(1e-9, poisson.cdf(hi-observed, lam)-poisson.cdf(lo-observed-1, lam))

sel=[]
cur=auc[(auc.duration_type.isin(['2-day','7-day']))&(auc.winning_bucket!='')&(~auc.auction_slug.str.contains('arch-|higher-bra|lower-bra',regex=True))]
for _,a in cur.iterrows():
    w=noonET(a.auction_slug,a['start_utc'].year)
    if not w: continue
    ns,ne=w; dur=a.duration_type
    if dur=='7-day' and ns<int(pd.Timestamp('2025-09-05',tz='UTC').timestamp()): continue
    if dur=='2-day' and ns<int(pd.Timestamp('2026-01-05',tz='UTC').timestamp()): continue
    blab=[b for b in buckets_by_slug.get(a.auction_slug,[]) if (a.auction_slug,b) in price_idx]
    if not blab: continue
    if obs(ns,ne)<=0: continue
    sel.append(dict(slug=a.auction_slug,dur=dur,ns=ns,ne=ne,winner=a['winning_bucket'],
                    branges=[(b,pbk(b)) for b in blab if pbk(b)]))
print(f"auctions: {len(sel)} (7d={sum(1 for x in sel if x['dur']=='7-day')}, 2d={sum(1 for x in sel if x['dur']=='2-day')})")

print(f"\n{'ttg':>5}{'gap':>6}{'series':>8}{'n_buys':>8}{'avg_pred_EV':>12}{'avg_realized':>13}{'win%':>7}{'PnL/auc':>9}")
for ttg in [3.0,2.0,1.0,0.5]:
    for gap in [0.03,0.05,0.10]:
        for series in ['7-day','2-day']:
            buys=[]; per_auc={}
            for a in sel:
                if a['dur']!=series: continue
                ns,ne=a['ns'],a['ne']; cps=int(ne-ttg*3600)
                if cps<=ns+3600: continue
                o=obs(ns,cps)
                rate=obs(cps-6*3600,cps)/6.0  # tweets/hour over last 6h
                lam=max(0.1, rate*ttg)
                worth={}
                for b,(lo,hi) in a['branges']: worth[b]=bracket_prob(lo,hi,o,lam)
                tot=sum(worth.values()) or 1; worth={b:v/tot for b,v in worth.items()}
                for b,_ in a['branges']:
                    p=price_at(a['slug'],b,cps)
                    if p is None: continue
                    q=worth[b]
                    if q-p>gap:
                        won=1.0 if b==a['winner'] else 0.0
                        buys.append((q-p, won-p)); per_auc.setdefault(a['slug'],[]).append(won-p)
            if not buys: continue
            pred=np.mean([x[0] for x in buys]); real=np.mean([x[1] for x in buys]); win=100*np.mean([1 if x[1]>0 else 0 for x in buys])
            pnl_auc=np.mean([sum(v) for v in per_auc.values()])
            print(f"{ttg:>5}{gap:>6.2f}{series:>8}{len(buys):>8}{pred:>12.3f}{real:>13.3f}{win:>6.0f}%{pnl_auc:>9.3f}")
